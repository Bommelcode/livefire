"""PowerPoint-engine via COM-besturing.

Scope MVP:
- Eén actieve presentatie tegelijk (open + slideshow)
- Acties: open, next-slide, previous-slide, goto-slide, close
- Audio + video + animaties + transities + hyperlinks blijven werken want
  PowerPoint blijft de daadwerkelijke speler; liveFire is alleen de
  cue-trigger.

Vereist: Windows + Microsoft PowerPoint geïnstalleerd. Engine degradeert
gracefully op machines zonder Office (alle calls return False met een
duidelijke foutmelding).
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from .registry import EngineStatus, register


# Optionele dependency — engine werkt degraded zonder.
_COM_OK = False
_COM_ERR = ""
if sys.platform == "win32":
    try:
        import win32com.client  # type: ignore[import-not-found]
        import pythoncom  # type: ignore[import-not-found]
        _COM_OK = True
    except Exception as _e:
        _COM_ERR = f"pywin32 niet geladen: {_e}"
else:
    _COM_ERR = "PowerPoint COM is alleen beschikbaar op Windows"


# COM-constanten die we anders dynamisch zouden moeten ophalen.
_PP_SHOW_TYPE_KIOSK = 1   # ppShowTypeKiosk — slideshow blijft draaien
_PP_SLIDE_SHOW_DONE = 5   # ppSlideShowDone
_PP_WINDOW_MINIMIZED = 2  # ppWindowMinimized — verbergt de editor-window


class PowerPointEngine(QObject):
    """Beheert één PowerPoint Application + actieve Presentation."""

    presentation_opened = pyqtSignal(str)   # file_path
    presentation_closed = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._app = None        # PowerPoint.Application (COM)
        self._presentation = None
        self._current_path: str = ""
        # Of we PowerPoint zelf hebben gestart (en dus mogen quitten bij
        # shutdown). Als de gebruiker PowerPoint al open had hebben we de
        # bestaande instance overgenomen — niet stiekem afsluiten.
        self._we_started_app = False

    @property
    def available(self) -> bool:
        return _COM_OK

    # ---- public API --------------------------------------------------------

    def open(self, file_path: str) -> tuple[bool, str]:
        """Open een .pptx en start direct de slideshow."""
        if not _COM_OK:
            return False, _COM_ERR
        path = Path(file_path)
        if not path.is_file():
            return False, f"Bestand niet gevonden: {path}"

        try:
            # COM moet per thread geïnitialiseerd worden; doe het hier zodat
            # de Qt-hoofdthread klaar is om PowerPoint te besturen.
            pythoncom.CoInitialize()
        except Exception:
            pass

        # Sluit eventuele vorige presentatie van ons.
        self._close_presentation_if_any()

        try:
            if self._app is None:
                # GetActiveObject gebruikt een lopende PowerPoint als die er
                # is, anders Dispatch() start 'm. We onthouden of we 'm zelf
                # opstartten zodat we niet abrupt iemands geopende slides
                # afsluiten.
                try:
                    self._app = win32com.client.GetActiveObject(
                        "PowerPoint.Application"
                    )
                    self._we_started_app = False
                except Exception:
                    self._app = win32com.client.Dispatch(
                        "PowerPoint.Application"
                    )
                    self._we_started_app = True
                self._app.Visible = True
        except Exception as e:
            return False, f"Kon PowerPoint niet starten: {e}"

        # Open zonder readonly-flag: sommige presentaties (Protected View,
        # buiten Trusted Locations, OneDrive-streams) weigeren read-only en
        # gooien dan een -2147352567 / "PowerPoint could not open the file".
        # WithWindow=True zorgt dat de slideshow z'n eigen fullscreen-venster
        # krijgt; PowerPoint kiest zelf het juiste output-scherm.
        full_path = str(path.resolve())
        try:
            self._presentation = self._app.Presentations.Open(full_path)
        except Exception as e:
            return False, f"Kon presentatie niet openen: {e}"

        # Minimaliseer de editor-window meteen — de slideshow draait straks
        # in een eigen fullscreen window dat hier los van staat. Anders zie
        # je de PowerPoint-UI achter de slideshow.
        try:
            for i in range(1, self._presentation.Windows.Count + 1):
                self._presentation.Windows(i).WindowState = _PP_WINDOW_MINIMIZED
        except Exception:
            pass

        try:
            settings = self._presentation.SlideShowSettings
            settings.ShowType = _PP_SHOW_TYPE_KIOSK
            slideshow_window = settings.Run()
        except Exception as e:
            return False, f"Kon slideshow niet starten: {e}"

        # PowerPoint slideshow opent vaak achter onze Qt-mainwindow (zeker
        # na een fullscreen video-cue). We forceren 'm naar voren via:
        #   1. Hef Windows' foreground-lock op (ASFW_ANY = -1)
        #   2. Activeer PowerPoint op COM-niveau
        #   3. Activate() op de SlideShowWindow zelf
        #   4. Win32 SetForegroundWindow + SwitchToThisWindow op de HWND,
        #      met een Alt-keystroke om de focus-token vrij te geven.
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
        try:
            self._app.Activate()
        except Exception:
            pass

        # Geef PowerPoint even tijd om de slideshow daadwerkelijk te
        # tonen voordat we de HWND opvragen — anders is HWND nog 0.
        hwnd = 0
        for _ in range(20):  # ~1 s
            try:
                hwnd = int(slideshow_window.HWND)
            except Exception:
                hwnd = 0
            if hwnd:
                break
            time.sleep(0.05)

        try:
            slideshow_window.Activate()
        except Exception:
            pass

        if hwnd:
            try:
                user32 = ctypes.windll.user32
                # VK_MENU = 0x12 ; KEYEVENTF_KEYUP = 0x02
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 0x02, 0)
                user32.SetForegroundWindow(hwnd)
                # SwitchToThisWindow is undocumented maar betrouwbaar voor
                # cross-process focus na een net-getoonde window.
                user32.SwitchToThisWindow(hwnd, True)
                user32.BringWindowToTop(hwnd)
            except Exception:
                pass

        self._current_path = str(path)
        self.presentation_opened.emit(self._current_path)
        return True, ""

    def next_slide(self) -> tuple[bool, str]:
        view = self._slideshow_view()
        if view is None:
            return False, "Geen actieve slideshow"
        try:
            view.Next()
            return True, ""
        except Exception as e:
            return False, f"Volgende slide mislukt: {e}"

    def previous_slide(self) -> tuple[bool, str]:
        view = self._slideshow_view()
        if view is None:
            return False, "Geen actieve slideshow"
        try:
            view.Previous()
            return True, ""
        except Exception as e:
            return False, f"Vorige slide mislukt: {e}"

    def goto_slide(self, slide_number: int) -> tuple[bool, str]:
        view = self._slideshow_view()
        if view is None:
            return False, "Geen actieve slideshow"
        if slide_number < 1:
            return False, "Slide-nummer moet ≥ 1 zijn"
        try:
            view.GotoSlide(int(slide_number))
            return True, ""
        except Exception as e:
            return False, f"Goto slide mislukt: {e}"

    def close(self) -> tuple[bool, str]:
        """Stop de slideshow en sluit de presentatie."""
        self._close_presentation_if_any()
        return True, ""

    def is_slideshow_active(self) -> bool:
        return self._slideshow_view() is not None

    def shutdown(self) -> None:
        self._close_presentation_if_any()
        if self._app is not None and self._we_started_app:
            try:
                self._app.Quit()
            except Exception:
                pass
        self._app = None
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

    # ---- intern ------------------------------------------------------------

    def _slideshow_view(self):
        if self._presentation is None:
            return None
        try:
            window = self._presentation.SlideShowWindow
        except Exception:
            return None
        if window is None:
            return None
        try:
            view = window.View
        except Exception:
            return None
        # Als de slideshow al gedaan is, geeft View.State 5 (Done) terug.
        try:
            if int(view.State) == _PP_SLIDE_SHOW_DONE:
                return None
        except Exception:
            pass
        return view

    def _close_presentation_if_any(self) -> None:
        if self._presentation is None:
            return
        # End slideshow als die nog draait.
        try:
            window = self._presentation.SlideShowWindow
            if window is not None:
                window.View.Exit()
        except Exception:
            pass
        try:
            self._presentation.Close()
        except Exception:
            pass
        self._presentation = None
        self._current_path = ""
        # Minimaliseer de PowerPoint Application zelf zodat de (nu lege)
        # editor niet over een volgende video- of presentatie-cue blijft
        # staan. We laten 'm wel draaien — een volgende Open is dan snel.
        if self._app is not None:
            try:
                self._app.WindowState = _PP_WINDOW_MINIMIZED
            except Exception:
                pass
        self.presentation_closed.emit()


# ---- status-registratie ----------------------------------------------------

def register_status(engine: PowerPointEngine | None = None) -> None:
    if not _COM_OK:
        register(EngineStatus(
            name="PowerPoint (COM)",
            available=False,
            detail=_COM_ERR or "pywin32 niet geladen",
            short="ppt",
        ))
        return
    register(EngineStatus(
        name="PowerPoint (COM)",
        available=True,
        detail="pywin32 + COM beschikbaar (vereist Microsoft PowerPoint)",
        short="ppt",
    ))
