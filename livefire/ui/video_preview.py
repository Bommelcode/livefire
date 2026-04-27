"""Inspector-preview voor video-cues: klein VLC-paneel + tijdlijn-widget
met sleepbare in- en uit-punt markers (live scrub)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFrame, QLabel

try:
    import vlc  # type: ignore[import-not-found]
    _VLC_OK = True
except Exception:
    vlc = None  # type: ignore[assignment]
    _VLC_OK = False


class TimelineWidget(QWidget):
    """Horizontale tijdlijn met sleepbare in/uit-markers. Geeft realtime
    scrub-positie door terwijl de gebruiker sleept."""

    in_changed = pyqtSignal(float)       # seconden, commit bij release
    out_changed = pyqtSignal(float)
    scrubbing = pyqtSignal(float)         # live, terwijl user sleept

    _HANDLE_W = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._duration: float = 0.0
        self._in_s: float = 0.0
        self._out_s: float = 0.0
        self._dragging: Optional[str] = None  # "in" | "out" | None

    # ---- public API -------------------------------------------------------

    def set_duration(self, seconds: float) -> None:
        self._duration = max(0.0, seconds)
        if self._out_s <= 0 or self._out_s > self._duration:
            self._out_s = self._duration
        self.update()

    def set_in_point(self, s: float) -> None:
        self._in_s = max(0.0, min(s, self._duration or s))
        self.update()

    def set_out_point(self, s: float) -> None:
        # 0 betekent "tot einde" in ons datamodel; toon dan de volledige duur.
        visual_out = s if s > 0 else self._duration
        self._out_s = max(self._in_s, min(visual_out, self._duration or visual_out))
        self.update()

    def in_point(self) -> float:
        return self._in_s

    def out_point(self) -> float:
        return self._out_s

    # ---- paint -------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        track_y = h // 2 - 4
        # Track background
        p.fillRect(0, track_y, w, 8, QColor("#2a2a2a"))
        if self._duration <= 0:
            p.setPen(QColor("#9a9a9a"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No video loaded")
            return
        # Active range (between in and out)
        x_in = self._time_to_x(self._in_s)
        x_out = self._time_to_x(self._out_s)
        p.fillRect(x_in, track_y, max(0, x_out - x_in), 8, QColor("#3aa2e6"))
        # Handles (in = groen, out = rood)
        self._draw_handle(p, x_in, h, QColor("#2e8b57"))
        self._draw_handle(p, x_out, h, QColor("#c0392b"))

    def _draw_handle(self, p: QPainter, x: int, h: int, color: QColor) -> None:
        w = self._HANDLE_W
        p.setBrush(QBrush(color))
        p.setPen(QPen(QColor("#e0e0e0"), 1))
        p.drawRect(x - w // 2, 2, w, h - 4)

    def _time_to_x(self, t: float) -> int:
        if self._duration <= 0:
            return 0
        return int(t / self._duration * self.width())

    def _x_to_time(self, x: float) -> float:
        if self.width() <= 0 or self._duration <= 0:
            return 0.0
        t = x / self.width() * self._duration
        return max(0.0, min(t, self._duration))

    # ---- interaction -------------------------------------------------------

    def mousePressEvent(self, e) -> None:
        if self._duration <= 0:
            return
        x = e.position().x()
        x_in = self._time_to_x(self._in_s)
        x_out = self._time_to_x(self._out_s)
        # Pak de dichtstbijzijnde handle.
        self._dragging = "in" if abs(x - x_in) <= abs(x - x_out) else "out"
        self._update_drag(x)

    def mouseMoveEvent(self, e) -> None:
        if self._dragging is None:
            return
        self._update_drag(e.position().x())

    def mouseReleaseEvent(self, _event) -> None:
        if self._dragging == "in":
            self.in_changed.emit(self._in_s)
        elif self._dragging == "out":
            self.out_changed.emit(self._out_s)
        self._dragging = None

    def _update_drag(self, x: float) -> None:
        t = self._x_to_time(x)
        if self._dragging == "in":
            self._in_s = min(t, self._out_s)
        else:
            self._out_s = max(t, self._in_s)
        self.scrubbing.emit(t)
        self.update()


class VideoPreviewWidget(QWidget):
    """Klein VLC-paneel + tijdlijn voor in/uit-punt scrubbing. Gebruikt een
    eigen VLC-instance met --no-audio zodat scrubben stil is en los staat
    van de hoofd-engine."""

    in_point_changed = pyqtSignal(float)
    out_point_changed = pyqtSignal(float)
    duration_detected = pyqtSignal(float)   # file-duur in seconden (cache)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.display = QFrame()
        self.display.setMinimumHeight(180)
        self.display.setStyleSheet("background: black; border: 1px solid #3a3a3a;")
        # Vraag een native handle alleen op dit widget; voorkomt dat Qt ook
        # alle parents (scrollarea/inspector/mainwindow) native maakt — dat
        # breekt keyboard focus-routing naar spinboxes.
        self.display.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.display.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        # Display-widget mag geen keyboard focus krijgen; die hoort naar
        # de inspector-velden te gaan.
        self.display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.display)

        self.timeline = TimelineWidget()
        lay.addWidget(self.timeline)

        self.lbl_info = QLabel("—")
        self.lbl_info.setStyleSheet("color: #9a9a9a;")
        lay.addWidget(self.lbl_info)

        # VLC preview-player (eigen instance — geïsoleerd van de hoofd-engine).
        self._instance = None
        self._player = None
        if _VLC_OK:
            try:
                self._instance = vlc.Instance("--no-audio", "--quiet", "--no-video-title-show")  # type: ignore[union-attr]
                self._player = self._instance.media_player_new()
            except Exception:
                self._instance = None
                self._player = None

        self._duration: float = 0.0
        self._pending_hwnd = False
        self._current_path: str = ""

        # Debounce voor pauzeren ná een scrub-burst: terwijl de gebruiker sleept
        # of rapid klikt op spinbox-pijltjes houden we de player spelend zodat
        # VLC niet per scrub hoeft te re-decoderen (wat stottert).
        self._repause_timer = QTimer(self)
        self._repause_timer.setSingleShot(True)
        self._repause_timer.setInterval(150)
        self._repause_timer.timeout.connect(self._repause)

        self.timeline.scrubbing.connect(self._scrub_to)
        self.timeline.in_changed.connect(self.in_point_changed.emit)
        self.timeline.out_changed.connect(self.out_point_changed.emit)

    # ---- public API -------------------------------------------------------

    def load(self, path: str, in_s: float = 0.0, out_s: float = 0.0) -> None:
        """Laad een video en toon het eerste frame. Zet in/uit-markers naar
        de meegegeven waardes (out_s=0 betekent "tot einde")."""
        self._current_path = path
        if not path or not Path(path).is_file() or self._player is None:
            self._duration = 0.0
            self.timeline.set_duration(0.0)
            self.lbl_info.setText("—")
            if self._player is not None:
                self._player.stop()
            return
        self._attach_hwnd_if_needed()
        media = self._instance.media_new(path)  # type: ignore[union-attr]
        self._player.set_media(media)
        self._player.play()
        # libVLC heeft wisselend veel tijd nodig om metadata te vullen; we
        # pollen get_length() tot 'ie > 0 is of een ruime timeout verstrijkt.
        self._load_retries = 0
        QTimer.singleShot(100, lambda: self._after_load(in_s, out_s))

    def set_markers(self, in_s: float, out_s: float) -> None:
        """Zet timeline-markers zonder de video opnieuw te laden."""
        self.timeline.set_in_point(in_s)
        self.timeline.set_out_point(out_s)

    def scrub_to(self, seconds: float) -> None:
        """Spring de preview-player naar een specifiek tijdstip. Gebruikt door
        de inspector als de spinboxen het in- of uit-punt verplaatsen."""
        self._scrub_to(seconds)

    def shutdown(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
                self._player.release()
            except Exception:
                pass
        if self._instance is not None:
            try:
                self._instance.release()
            except Exception:
                pass
        self._player = None
        self._instance = None

    # ---- intern ------------------------------------------------------------

    def _attach_hwnd_if_needed(self) -> None:
        if self._player is None or self._pending_hwnd:
            return
        try:
            self._player.set_hwnd(int(self.display.winId()))
            self._pending_hwnd = True
        except Exception:
            pass

    def _after_load(self, in_s: float, out_s: float) -> None:
        if self._player is None:
            return
        length_ms = self._player.get_length()
        if length_ms <= 0 and self._load_retries < 30:
            # ~3s totaal (30 × 100 ms) om metadata binnen te laten komen
            self._load_retries += 1
            QTimer.singleShot(100, lambda: self._after_load(in_s, out_s))
            return
        self._player.set_pause(True)
        self._duration = length_ms / 1000.0 if length_ms > 0 else 0.0
        self.timeline.set_duration(self._duration)
        self.timeline.set_in_point(in_s)
        self.timeline.set_out_point(out_s)
        if in_s > 0:
            self._scrub_to(in_s)
        self._update_info()
        if self._duration > 0:
            self.duration_detected.emit(self._duration)

    def _scrub_to(self, seconds: float) -> None:
        if self._player is None or self._duration <= 0:
            return
        # Clamp net vóór het einde: libVLC komt in Ended state zodra je op
        # (of voorbij) het laatste frame seekt, en negeert daarna verdere
        # set_time() calls — de preview lijkt dan definitief te hangen.
        seconds = max(0.0, min(seconds, self._duration - 0.05))
        # Recover als de player toch al Ended/Stopped is (bijv. na natuurlijk
        # einde of een eerdere end-seek): herstart voor de set_time.
        self._ensure_playable()
        # libVLC op Windows rendert geen nieuw frame als je set_time() op een
        # paused player aanroept — blijf tijdens een scrub-burst gewoon
        # spelend en pauzeer pas na 150 ms stilte (zie _repause_timer).
        self._player.set_pause(False)
        self._player.set_time(int(seconds * 1000))
        self._update_info(scrub=seconds)
        self._repause_timer.start()

    def _ensure_playable(self) -> None:
        """Herstart player als ie in Ended/Stopped/Error state staat, anders
        negeert libVLC verdere set_time() calls."""
        if self._player is None or not _VLC_OK:
            return
        try:
            state = self._player.get_state()
        except Exception:
            return
        if state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):  # type: ignore[union-attr]
            try:
                self._player.stop()
                self._player.play()
            except Exception:
                pass

    def _repause(self) -> None:
        if self._player is not None:
            try:
                self._player.set_pause(True)
            except Exception:
                pass

    def _update_info(self, scrub: float | None = None) -> None:
        if self._duration <= 0:
            self.lbl_info.setText("—")
            return
        in_s = self.timeline.in_point()
        out_s = self.timeline.out_point()
        parts = [f"Duur: {self._duration:.1f}s",
                 f"In: {in_s:.2f}s",
                 f"Uit: {out_s:.2f}s"]
        if scrub is not None:
            parts.append(f"Scrub: {scrub:.2f}s")
        self.lbl_info.setText("  ·  ".join(parts))
