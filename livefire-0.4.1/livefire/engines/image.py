"""Image-engine: toont stills fullscreen met optionele fade-in/-out.

Eigenstandige Qt-implementatie (geen libVLC). Slides en losse afbeeldingen
zijn statische bitmaps — die zouden via libVLC's "image-duration" werken
maar dat geeft koppeling aan VLC's still-image-quirks die we niet nodig
hebben. Een QPixmap op een frameless fullscreen window is genoeg.

Semantiek:

* Per output-scherm is er één 'eigenaar' (de laatst gestarte cue), maar
  meerdere cues kunnen tegelijk op hetzelfde scherm zichtbaar zijn
  tijdens een crossfade-overgang. Wanneer een nieuwe image-cue start
  op een scherm waar al een cue draait, krijgt de oude een fade-out
  gelijk aan de fade-in van de nieuwe; beide windows zijn kort
  gelijktijdig zichtbaar (nieuwere bovenop, op basis van Qt's
  creatie-volgorde van top-most Tool-windows).
* Bij ``fade_in == 0`` (harde cut) wordt de vorige direct gesloten
  zodat z'n window-resources niet onnodig in geheugen blijven hangen.
* `cue.duration > 0`: image is `duration` seconden zichtbaar, daarna
  fade-out + dichtklappen. Engine markeert intern als "klaar".
* `cue.duration == 0`: image blijft zichtbaar tot vervanging door een
  volgende image-cue op hetzelfde scherm, een Stop-cue, of `shutdown()`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtCore import (
    Qt, QObject, QPropertyAnimation, QTimer, pyqtSignal, QEasingCurve,
)
from PyQt6.QtGui import QGuiApplication, QPixmap
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout

from .registry import EngineStatus, register


# ---- ImageWindow -----------------------------------------------------------

class ImageWindow(QWidget):
    """Frameless fullscreen window met een geschaalde QPixmap erin.

    `windowOpacity` (0..1) is animeerbaar via QPropertyAnimation; we gebruiken
    dat voor fade-in/-out. Achtergrond is zwart zodat een non-fullscreen
    aspect-ratio-mismatch niet de desktop laat zien.
    """

    def __init__(self, file_path: str, screen_index: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool   # geen taskbar-entry
        )
        # Bewust GEEN WA_DeleteOnClose: de engine beheert lifecycle expliciet
        # via close() + deleteLater(). Auto-delete zou een levende
        # QPropertyAnimation-target kunnen wegtrekken → crash.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet("background-color: black;")
        # Begin op 0 zodat een eventuele fade-in geen 100%-flash op Windows
        # geeft tussen show() en de eerste animation-frame.
        self.setWindowOpacity(0.0)

        self._pixmap = QPixmap(file_path)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background-color: black;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)

        # Plaats op het juiste scherm
        screens = QGuiApplication.screens()
        if screens:
            idx = max(0, min(screen_index, len(screens) - 1))
            self.setGeometry(screens[idx].geometry())

    def show_fullscreen(self) -> None:
        self.showFullScreen()
        self._rescale()

    def resizeEvent(self, ev) -> None:  # type: ignore[override]
        super().resizeEvent(ev)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap.isNull():
            return
        # High-DPI aware scaling: schaal de pixmap naar het FYSIEKE aantal
        # pixels (logical size × devicePixelRatio), dan zet de DPR op de
        # output-pixmap zodat Qt 'm 1:1 op de fysieke pixels rendert in
        # plaats van een logical-size pixmap nog eens te upscalen. Op een
        # 4K projector met 200% scaling (1920×1080 logical, 3840×2160
        # fysiek) levert dit een scherp beeld in plaats van een uitgerekte
        # 1080p versie.
        dpr = self.devicePixelRatioF()
        target = self.size() * dpr
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self._label.setPixmap(scaled)


# ---- ImageEngine -----------------------------------------------------------

@dataclass
class _Active:
    cue_id: str
    window: ImageWindow
    screen_index: int
    started_at: float
    duration: float        # 0 = oneindig
    fade_out_s: float
    fade_in_anim: QPropertyAnimation | None = None
    fade_out_anim: QPropertyAnimation | None = None
    auto_stop_timer: QTimer | None = None
    stop_triggered: bool = False


class ImageEngine(QObject):
    """Beheert image-windows per cue. Alles op de Qt-hoofdthread."""

    cue_finished = pyqtSignal(str)  # cue_id — voor evt. UI-feedback later

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._active: dict[str, _Active] = {}
        # screen_index → cue_id (laatste image op dit scherm)
        self._screen_owner: dict[int, str] = {}

    # ---- public API --------------------------------------------------------

    @property
    def available(self) -> bool:
        # Qt is een harde dependency van de app — engine is altijd beschikbaar.
        return True

    def play(
        self,
        cue_id: str,
        file_path: str,
        screen_index: int = 0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        duration: float = 0.0,
    ) -> tuple[bool, str]:
        """Toon een image fullscreen op het opgegeven scherm.

        Crossfade-gedrag bij vervanging op hetzelfde scherm:

        * Als de inkomende cue een ``fade_in > 0`` heeft, krijgt de vorige
          cue (mits die nog niet zelf aan het stoppen is) een fade-out
          van dezelfde duur, terwijl het nieuwe window erboven infade't.
          Beide windows blijven kort gelijktijdig zichtbaar — de
          nieuwere staat door creatie-volgorde bovenop.
        * Bij ``fade_in == 0`` (harde cut) sluiten we de vorige direct
          zodat z'n pixmap niet onnodig in geheugen blijft staan.
        * Een vorige cue die zelf al een fade-out had ingezet (manueel
          gestopt of duration verlopen) laten we ongemoeid uitlopen
          onder de nieuwe — z'n eigen fade-tijd respecteren.
        """
        if not file_path:
            return False, "Geen bestand opgegeven"

        # Laad een test-pixmap om te checken of het bestand leesbaar is.
        # Sommige PNG-paden falen pas bij paint — vroeg falen geeft een
        # bruikbare foutmelding terug aan de controller.
        probe = QPixmap(file_path)
        if probe.isNull():
            return False, f"Kon afbeelding niet laden: {file_path}"

        # Eerdere cue op zelfde scherm: laat 'm crossfaden in plaats van
        # hard-killen.
        prev_cue = self._screen_owner.get(screen_index)
        if prev_cue and prev_cue != cue_id:
            prev_active = self._active.get(prev_cue)
            if prev_active is not None and not prev_active.stop_triggered:
                if fade_in > 0:
                    # Trigger prev z'n fade-out met de duur van onze
                    # fade-in zodat ze ritmisch crossfaden.
                    self.stop_cue(prev_cue, fade_out=fade_in)
                else:
                    # Harde cut: prev meteen weg zodat z'n window-resources
                    # niet onnodig in geheugen blijven hangen.
                    self._hard_close(prev_cue)
            # else: prev had al een eigen fade-out lopen — niet overrulen.

        # Sluit een eventuele lopende cue met hetzelfde id (re-fire).
        if cue_id in self._active:
            self._hard_close(cue_id)

        win = ImageWindow(file_path, screen_index=screen_index)
        # ImageWindow start op opacity=0; show eerst, daarna animeren of
        # direct op 1 zetten. Dit voorkomt een 100%-flash op Windows.
        win.show_fullscreen()

        active = _Active(
            cue_id=cue_id,
            window=win,
            screen_index=screen_index,
            started_at=time.monotonic(),
            duration=max(0.0, duration),
            fade_out_s=max(0.0, fade_out),
        )

        if fade_in > 0:
            # Anim-parent op het window zodat het samen met het window dood
            # gaat (anim probeert anders een gedelete target te animeren).
            anim = QPropertyAnimation(win, b"windowOpacity", win)
            anim.setDuration(int(fade_in * 1000))
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            anim.start()
            active.fade_in_anim = anim
        else:
            win.setWindowOpacity(1.0)

        if active.duration > 0:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda cid=cue_id: self.stop_cue(cid, active.fade_out_s))
            t.start(int(active.duration * 1000))
            active.auto_stop_timer = t

        self._active[cue_id] = active
        self._screen_owner[screen_index] = cue_id
        return True, ""

    def stop_cue(self, cue_id: str, fade_out: float = 0.0) -> None:
        """Fade out + sluit het window van deze cue."""
        a = self._active.get(cue_id)
        if a is None:
            return
        if a.stop_triggered:
            return
        a.stop_triggered = True

        # Cancel auto-stop timer (we handelen 'm hier zelf af).
        if a.auto_stop_timer is not None:
            a.auto_stop_timer.stop()

        f = max(0.0, fade_out if fade_out > 0 else a.fade_out_s)
        if f <= 0:
            self._finalize_close(cue_id)
            return

        # Stop een nog lopende fade-in zodat we niet beide tegelijk animeren.
        if a.fade_in_anim is not None:
            a.fade_in_anim.stop()

        # Anim parent op window — zie play() voor rationale.
        anim = QPropertyAnimation(a.window, b"windowOpacity", a.window)
        anim.setDuration(int(f * 1000))
        anim.setStartValue(a.window.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.finished.connect(lambda cid=cue_id: self._finalize_close(cid))
        anim.start()
        a.fade_out_anim = anim

    def stop_all(self) -> None:
        for cid in list(self._active.keys()):
            self._hard_close(cid)

    def is_playing(self, cue_id: str) -> bool:
        """True zolang de engine deze cue actief beheert — inclusief tijdens
        een fade-out. Gaat pas False wanneer ``_finalize_close`` of
        ``_hard_close`` de entry uit ``_active`` heeft verwijderd. Komt
        overeen met de semantiek van ``VideoEngine.is_playing()`` zodat de
        controller-tick voor IMAGE niet vroegtijdig afrondt en `post_wait`
        pas na de fade-out start."""
        return cue_id in self._active

    def get_remaining(self, cue_id: str) -> float | None:
        a = self._active.get(cue_id)
        if a is None or a.duration <= 0:
            return None
        elapsed = time.monotonic() - a.started_at
        return max(0.0, a.duration - elapsed)

    def shutdown(self) -> None:
        self.stop_all()

    # ---- intern ------------------------------------------------------------

    def _hard_close(self, cue_id: str) -> None:
        a = self._active.pop(cue_id, None)
        if a is None:
            return
        if a.auto_stop_timer is not None:
            a.auto_stop_timer.stop()
        if a.fade_in_anim is not None:
            a.fade_in_anim.stop()
        if a.fade_out_anim is not None:
            a.fade_out_anim.stop()
        try:
            a.window.close()
            a.window.deleteLater()
        except Exception:
            pass
        if self._screen_owner.get(a.screen_index) == cue_id:
            self._screen_owner.pop(a.screen_index, None)
        self.cue_finished.emit(cue_id)

    def _finalize_close(self, cue_id: str) -> None:
        a = self._active.pop(cue_id, None)
        if a is None:
            return
        try:
            a.window.close()
            a.window.deleteLater()
        except Exception:
            pass
        if self._screen_owner.get(a.screen_index) == cue_id:
            self._screen_owner.pop(a.screen_index, None)
        self.cue_finished.emit(cue_id)


# ---- status-registratie ----------------------------------------------------

def register_status(engine: ImageEngine | None = None) -> None:
    register(EngineStatus(
        name="Image (Qt)",
        available=True,
        detail="Fullscreen still-images via QPixmap.",
        short="img",
    ))
