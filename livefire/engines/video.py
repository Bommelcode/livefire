"""Video-engine op basis van python-vlc (libVLC).

Scope v0.6.0 MVP:
- Eén VLC-player per spelende cue
- Per-cue keuze van output-scherm (fullscreen op QScreen index)
- Fade-in / fade-out via Qt window-opacity animation
- Audio van de video via libVLC's eigen output (audio-device te kiezen
  in Voorkeuren, separaat van de sounddevice audio-engine)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QObject, QPropertyAnimation, QEasingCurve, pyqtSignal, Qt, QTimer,
)
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget

from .registry import EngineStatus, register

# Optionele dependency — engine werkt degraded zonder.
try:
    import vlc  # type: ignore[import-not-found]
    _VLC_OK = True
    _VLC_ERR = ""
    _VLC_VERSION = ""
    try:
        v = vlc.libvlc_get_version()
        _VLC_VERSION = v.decode() if isinstance(v, bytes) else str(v)
    except Exception:
        pass
except Exception as e:
    vlc = None  # type: ignore[assignment]
    _VLC_OK = False
    _VLC_ERR = str(e)
    _VLC_VERSION = ""


def list_screens() -> list[tuple[int, str]]:
    """(index, label) voor elk beschikbaar scherm via QGuiApplication."""
    out: list[tuple[int, str]] = []
    for i, sc in enumerate(QGuiApplication.screens()):
        geo = sc.geometry()
        label = f"{i}: {sc.name()} ({geo.width()}×{geo.height()})"
        out.append((i, label))
    return out


def list_audio_devices(instance: "vlc.Instance | None" = None) -> list[tuple[str, str]]:
    """(device_id, naam) paren van VLC's audio-output van de huidige module.
    Leeg als libVLC niet beschikbaar is."""
    if not _VLC_OK:
        return []
    inst = instance or vlc.Instance()  # type: ignore[union-attr]
    mp = inst.media_player_new()
    out: list[tuple[str, str]] = []
    try:
        d = mp.audio_output_device_enum()
        while d:
            dev = d.contents
            dev_id = dev.device.decode() if dev.device else ""
            dev_name = dev.description.decode() if dev.description else dev_id
            out.append((dev_id, dev_name))
            d = dev.next
    finally:
        mp.release()
    return out


class VideoWindow(QWidget):
    """Frameless fullscreen-widget waar libVLC in rendert. Qt beheert de
    window-opacity zodat fade-in / fade-out via QPropertyAnimation kunnen."""

    def __init__(self, screen_index: int = 0, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setStyleSheet("background-color: black;")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        screens = QGuiApplication.screens()
        if not screens:
            self.setGeometry(0, 0, 800, 600)
        else:
            idx = max(0, min(screen_index, len(screens) - 1))
            self.setGeometry(screens[idx].geometry())
        self.setWindowOpacity(0.0)

    def hwnd_id(self) -> int:
        """Native window-handle om aan libVLC te geven (Windows HWND)."""
        return int(self.winId())


class VideoEngine(QObject):
    """Beheert één VLC-Instance en een dict van playing cue → (player, window)."""

    cue_finished = pyqtSignal(str)   # cue_id — eindigt van nature

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._instance: "vlc.Instance | None" = None
        if _VLC_OK:
            try:
                self._instance = vlc.Instance("--no-video-title-show", "--quiet")  # type: ignore[union-attr]
            except Exception as e:
                self._instance = None
                # Blijf leven in degraded mode.
                global _VLC_ERR
                _VLC_ERR = str(e)
        self._playing: dict[str, dict] = {}   # cue_id → {"player", "window", "fade_anim"}
        self._audio_device: str = ""

    @property
    def available(self) -> bool:
        return _VLC_OK and self._instance is not None

    def set_audio_device(self, device_id: str) -> None:
        """Sla het gekozen VLC audio-device op; wordt toegepast op nieuwe players."""
        self._audio_device = device_id or ""

    def play_file(
        self,
        cue_id: str,
        file_path: str,
        screen_index: int = 0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        start_offset: float = 0.0,
        end_offset: float = 0.0,
    ) -> tuple[bool, str]:
        if not self.available:
            return False, _VLC_ERR or "libVLC niet beschikbaar"
        path = Path(file_path)
        if not path.is_file():
            return False, f"Bestand niet gevonden: {path}"
        # Bestaande player voor deze cue? Stop eerst.
        if cue_id in self._playing:
            self.stop_cue(cue_id, fade_out=0.0)

        window = VideoWindow(screen_index=screen_index)
        window.showFullScreen()
        QGuiApplication.processEvents()

        player = self._instance.media_player_new()  # type: ignore[union-attr]
        player.set_hwnd(window.hwnd_id())
        if self._audio_device:
            try:
                player.audio_output_device_set(None, self._audio_device)
            except Exception:
                pass

        # In/uit-punt via media-opties. libVLC snapt :start-time / :stop-time.
        media = self._instance.media_new(str(path))  # type: ignore[union-attr]
        if start_offset > 0:
            media.add_option(f":start-time={start_offset:.3f}")
        if end_offset > 0:
            media.add_option(f":stop-time={end_offset:.3f}")
        player.set_media(media)
        player.play()

        # Fade-in via Qt window-opacity animation.
        if fade_in > 0:
            anim = QPropertyAnimation(window, b"windowOpacity")
            anim.setDuration(int(fade_in * 1000))
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            anim.start()
        else:
            window.setWindowOpacity(1.0)
            anim = None

        self._playing[cue_id] = {
            "player": player,
            "window": window,
            "media": media,
            "fade_anim": anim,
            "fade_out_s": fade_out,
            "stop_ms": int(end_offset * 1000) if end_offset > 0 else 0,
        }

        # Detecteer natuurlijk einde via VLC event.
        em = player.event_manager()
        em.event_attach(
            vlc.EventType.MediaPlayerEndReached,  # type: ignore[union-attr]
            lambda _e, cid=cue_id: QTimer.singleShot(0, lambda: self._on_end_reached(cid)),
        )
        return True, ""

    def stop_cue(self, cue_id: str, fade_out: float = 0.0) -> None:
        entry = self._playing.get(cue_id)
        if entry is None:
            return
        window = entry["window"]
        player = entry["player"]
        duration_s = fade_out if fade_out > 0 else entry.get("fade_out_s", 0.0)
        if duration_s > 0:
            anim = QPropertyAnimation(window, b"windowOpacity")
            anim.setDuration(int(duration_s * 1000))
            anim.setStartValue(window.windowOpacity())
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            anim.finished.connect(lambda cid=cue_id: self._hard_stop(cid))
            entry["fade_anim"] = anim
            anim.start()
        else:
            self._hard_stop(cue_id)

    def stop_all(self) -> None:
        for cid in list(self._playing.keys()):
            self._hard_stop(cid)

    def is_playing(self, cue_id: str) -> bool:
        """True zolang VLC actief rendert. False zodra de player in
        Ended/Stopped/Error-state komt — zo detecteert de controller
        natuurlijk einde (voor AUTO_FOLLOW en fade-out-trigger)."""
        entry = self._playing.get(cue_id)
        if entry is None:
            return False
        if not _VLC_OK:
            return True
        try:
            state = entry["player"].get_state()
        except Exception:
            return True
        return state not in (
            vlc.State.Ended,    # type: ignore[union-attr]
            vlc.State.Stopped,  # type: ignore[union-attr]
            vlc.State.Error,    # type: ignore[union-attr]
        )

    def get_remaining(self, cue_id: str) -> float | None:
        entry = self._playing.get(cue_id)
        if entry is None:
            return None
        player = entry["player"]
        try:
            length_ms = player.get_length()
            pos_ms = player.get_time()
        except Exception:
            return None
        if length_ms <= 0:
            return None
        # Respecteer :stop-time: bij een getrimd uit-punt moet de countdown
        # daarvandaan tellen, niet vanaf de file-lengte.
        stop_ms = entry.get("stop_ms") or 0
        effective_end_ms = stop_ms if 0 < stop_ms <= length_ms else length_ms
        return max(0.0, (effective_end_ms - pos_ms) / 1000.0)

    def shutdown(self) -> None:
        self.stop_all()
        if self._instance is not None:
            try:
                self._instance.release()
            except Exception:
                pass
        self._instance = None

    # ---- intern ------------------------------------------------------------

    def _hard_stop(self, cue_id: str) -> None:
        entry = self._playing.pop(cue_id, None)
        if entry is None:
            return
        try:
            entry["player"].stop()
            entry["player"].release()
        except Exception:
            pass
        try:
            entry["window"].close()
            entry["window"].deleteLater()
        except Exception:
            pass

    def _on_end_reached(self, cue_id: str) -> None:
        """Draait op UI-thread via QTimer.singleShot. Signaleer aan de
        controller dat deze cue natuurlijk klaar is (voor AUTO_FOLLOW)."""
        if cue_id in self._playing:
            # Laat de controller beslissen; die zal stop_cue met eventueel
            # fade-out aanroepen. Wij merken 'm hier alleen voor de signaal.
            self.cue_finished.emit(cue_id)


# ---- status-registratie ----------------------------------------------------

def register_status(engine: VideoEngine | None = None) -> None:
    if not _VLC_OK:
        register(EngineStatus(
            name="Video (libVLC)",
            available=False,
            detail=f"python-vlc niet geladen: {_VLC_ERR}",
            short="video",
        ))
        return
    if engine is None or not engine.available:
        register(EngineStatus(
            name="Video (libVLC)",
            available=False,
            detail=_VLC_ERR or "libVLC-instance niet opgestart",
            short="video",
        ))
        return
    detail = f"libVLC {_VLC_VERSION}" if _VLC_VERSION else "libVLC OK"
    register(EngineStatus(
        name="Video (libVLC)",
        available=True,
        detail=detail,
        short="video",
    ))
