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
import zipfile
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from .registry import EngineStatus, register


# ---- pure-Python helpers (geen PowerPoint of pywin32 nodig) ---------------

def is_com_available() -> bool:
    """True wanneer pywin32 + PowerPoint COM bruikbaar zijn op deze
    machine. Gebruikt door de PPT-import-dialog om de slides-optie
    al-dan-niet aan te bieden."""
    return _COM_OK


def count_slides(file_path: str) -> int | None:
    """Tel het aantal slides in een .pptx/.pptm zonder PowerPoint te starten.

    .pptx en .pptm zijn ZIP-archieven volgens de OpenXML-spec; iedere slide
    heeft een eigen ``ppt/slides/slideN.xml``. Tellen gaat dus puur via
    zipfile + filtering. Voor het legacy binary ``.ppt``-formaat geven we
    ``None`` terug — dat zou pywin32 + COM vereisen, en daar willen we niet
    op vertrouwen tijdens een drag-drop (PowerPoint zou starten alleen om te
    tellen).

    Edge: het aantal fysieke slides kan in zeldzame gevallen afwijken van
    het aantal slides in slideshow-volgorde (verborgen slides, custom shows).
    Voor de import-flow gebruiken we het fysieke aantal — dat is wat
    ``Slide.GotoSlide(N)`` indexeert.
    """
    ext = Path(file_path).suffix.lower()
    if ext not in {".pptx", ".pptm"}:
        return None
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return sum(
                1
                for name in zf.namelist()
                if name.startswith("ppt/slides/slide")
                and name.endswith(".xml")
                and "/_rels/" not in name
            )
    except (zipfile.BadZipFile, OSError, KeyError):
        return None


def export_slides_to_png(
    file_path: str,
    output_dir: str,
    max_dim: int = 1920,
    progress_callback=None,
) -> tuple[bool, list[str], str]:
    """Exporteer iedere slide naar een PNG via PowerPoint COM.

    Vereist Windows + Microsoft PowerPoint geïnstalleerd. Op andere
    platforms of zonder pywin32 retourneert deze functie ``(False, [],
    "...")``.

    Resolutie wordt aspect-correct bepaald op basis van
    ``Presentation.PageSetup.SlideWidth/SlideHeight`` (PowerPoint-points).
    De langste zijde wordt geschaald naar ``max_dim`` (default 1920); de
    andere zijde volgt evenredig. Zo blijven 4:3 en 16:9 presentaties
    onvervormd.

    Bestandsnamen volgen ``slide_001.png``, ``slide_002.png``, ... — drie
    cijfers padding zodat alfabetische sortering met natuurlijke volgorde
    overeenkomt tot 999 slides.

    `progress_callback(current, total)` (optioneel) wordt aangeroepen na
    iedere geslaagde slide-export, zodat een UI een progressbar kan
    bijwerken. Geeft het callback ``True`` terug, dan wordt de export
    afgebroken (cancel-knop).

    Returnt ``(ok, list_of_paths, error_message)``.
    """
    if not _COM_OK:
        return False, [], _COM_ERR or "PowerPoint COM niet beschikbaar"

    src = Path(file_path)
    if not src.is_file():
        return False, [], f"Bestand niet gevonden: {src}"

    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, [], f"Kon output-folder niet aanmaken ({out_dir}): {e}"

    try:
        pythoncom.CoInitialize()
    except Exception:
        pass

    app = None
    presentation = None
    we_started_app = False
    try:
        try:
            app = win32com.client.GetActiveObject("PowerPoint.Application")
        except Exception:
            app = win32com.client.Dispatch("PowerPoint.Application")
            we_started_app = True
        # PowerPoint vereist Visible=True voor de meeste COM-operaties.
        # Een onzichtbare instance accepteert geen Presentations.Open.
        try:
            app.Visible = True
        except Exception:
            pass

        try:
            presentation = app.Presentations.Open(
                str(src.resolve()),
                ReadOnly=True,
                Untitled=False,
                WithWindow=False,
            )
        except Exception:
            # Sommige PowerPoint-versies/-paths weigeren WithWindow=False;
            # val terug op WithWindow=True (we zien 'm dan kort flitsen).
            try:
                presentation = app.Presentations.Open(str(src.resolve()))
            except Exception as e:
                return False, [], f"Kon presentatie niet openen: {e}"

        # Minimaliseer eventueel het editor-window zodat de gebruiker geen
        # PowerPoint-UI ziet flitsen tijdens export.
        try:
            for i in range(1, presentation.Windows.Count + 1):
                presentation.Windows(i).WindowState = _PP_WINDOW_MINIMIZED
        except Exception:
            pass

        slide_count = int(presentation.Slides.Count)
        if slide_count <= 0:
            return False, [], "Presentatie bevat geen slides"

        # Aspect-correcte target-dims via PageSetup.
        # SlideWidth/Height zijn in points (1 pt = 1/72 inch); we hebben
        # alleen de verhouding nodig.
        try:
            slide_w = float(presentation.PageSetup.SlideWidth)
            slide_h = float(presentation.PageSetup.SlideHeight)
        except Exception:
            slide_w, slide_h = 1280.0, 720.0  # 16:9 fallback
        if slide_w <= 0 or slide_h <= 0:
            slide_w, slide_h = 1280.0, 720.0
        if slide_w >= slide_h:
            target_w = int(max_dim)
            target_h = max(1, int(round(max_dim * slide_h / slide_w)))
        else:
            target_h = int(max_dim)
            target_w = max(1, int(round(max_dim * slide_w / slide_h)))

        paths: list[str] = []
        for i in range(1, slide_count + 1):
            target = out_dir / f"slide_{i:03d}.png"
            try:
                presentation.Slides(i).Export(
                    str(target), "PNG", target_w, target_h
                )
            except Exception as e:
                return False, paths, f"Export van slide {i} mislukt: {e}"
            paths.append(str(target))
            if progress_callback is not None:
                cancelled = bool(progress_callback(i, slide_count))
                if cancelled:
                    return False, paths, "Geannuleerd"

        return True, paths, ""
    finally:
        if presentation is not None:
            try:
                # Markeer als 'opgeslagen' zodat Close() nooit een save-
                # prompt triggert. Slide.Export modificeert het document
                # niet, maar PowerPoint kan om interne redenen toch een
                # 'modified' flag zetten — defensief afvangen.
                presentation.Saved = True
            except Exception:
                pass
            try:
                presentation.Close()
            except Exception:
                pass
        if app is not None and we_started_app:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


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
