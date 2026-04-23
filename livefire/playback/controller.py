"""Playback controller. Orchestreert GO-acties, pre/post-waits,
continue-modes en stuurt cues door naar de juiste engines.

Draait op de Qt-hoofdthread; gebruikt een QTimer voor ticks zodat we
consistent zijn met de rest van de app. De audio-engine heeft z'n eigen
thread (PortAudio callback) maar die raken we hier alleen via zijn API."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..cues import Cue, CueType, ContinueMode
from ..engines import AudioEngine
from ..workspace import Workspace


TICK_MS = 20  # 50 Hz tick — ruim voldoende voor cue-timing, voor audio doet
               # de PortAudio callback het sample-accurate werk.


@dataclass
class _Running:
    cue: Cue
    started_at: float
    phase: str = "pre_wait"   # pre_wait | action | post_wait | done
    phase_started_at: float = 0.0
    action_duration: float = 0.0   # berekend op moment van action-start


class PlaybackController(QObject):
    """Bezit de engines en rijdt de cue-lijst af wanneer de gebruiker GO
    indrukt. Signals laten de UI statuschanges tonen."""

    cue_state_changed = pyqtSignal(str)   # cue.id
    running_changed = pyqtSignal()

    def __init__(
        self,
        workspace: Workspace,
        parent: QObject | None = None,
        audio: AudioEngine | None = None,
    ):
        super().__init__(parent)
        self.workspace = workspace
        self.audio = audio if audio is not None else AudioEngine()
        self.audio.start()

        self._running: dict[str, _Running] = {}
        self._playhead_index: int = 0

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- workspace management ---------------------------------------------

    def set_workspace(self, ws: Workspace) -> None:
        self.stop_all()
        self.workspace = ws
        self._playhead_index = 0

    def shutdown(self) -> None:
        self._timer.stop()
        self.stop_all()
        self.audio.stop()

    # ---- transport ---------------------------------------------------------

    @property
    def playhead_index(self) -> int:
        return self._playhead_index

    def set_playhead(self, index: int) -> None:
        self._playhead_index = max(0, min(index, len(self.workspace.cues)))

    def go(self) -> None:
        """Start de cue op de playhead, schuif playhead door."""
        if self._playhead_index >= len(self.workspace.cues):
            return
        cue = self.workspace.cues[self._playhead_index]
        self._playhead_index += 1
        self._start_cue(cue)

    def stop_all(self) -> None:
        ids = list(self._running.keys())
        for cid in ids:
            self._stop_running(cid, finished=False)
        self.audio.stop_all()

    def stop_cue(self, cue_id: str) -> None:
        if cue_id in self._running:
            self._stop_running(cue_id, finished=False)
        self.audio.stop_cue(cue_id)

    # ---- cue-specifieke start-logica --------------------------------------

    def _start_cue(self, cue: Cue) -> None:
        now = time.monotonic()
        running = _Running(cue=cue, started_at=now, phase="pre_wait",
                           phase_started_at=now)
        self._running[cue.id] = running
        cue.state = "running"
        self.cue_state_changed.emit(cue.id)
        self.running_changed.emit()
        # pre_wait=0 wordt in _tick direct doorgeschakeld naar action

    def _begin_action(self, r: _Running) -> None:
        cue = r.cue
        r.phase = "action"
        r.phase_started_at = time.monotonic()

        t = cue.cue_type
        if t == CueType.AUDIO:
            ok = self.audio.play_file(
                cue_id=cue.id,
                file_path=cue.file_path,
                volume_db=cue.volume_db,
                loops=cue.loops,
                start_offset=cue.audio_start_offset,
                end_offset=cue.audio_end_offset,
            )
            if not ok:
                r.action_duration = 0.0
            else:
                r.action_duration = cue.duration if cue.duration > 0 else 0.0
                # 0 = laten lopen tot bestand op is (detecteren via audio.is_playing)

        elif t == CueType.WAIT:
            r.action_duration = cue.wait_duration

        elif t == CueType.STOP:
            target = cue.target_cue_id
            if target:
                self.stop_cue(target)
            else:
                self.stop_all()
            r.action_duration = 0.0

        elif t == CueType.FADE:
            target = cue.target_cue_id
            if target:
                self.audio.apply_fade(
                    target,
                    cue.fade_target_db,
                    cue.duration,
                    stops=cue.fade_stops_target,
                )
            r.action_duration = cue.duration

        elif t == CueType.START:
            target = cue.target_cue_id
            target_cue = self.workspace.find(target) if target else None
            if target_cue is not None and target_cue.id != cue.id:
                self._start_cue(target_cue)
            r.action_duration = 0.0

        elif t == CueType.GROUP:
            # Skeleton: group speelt alle kindcues parallel (list-mode).
            # v0.3.x kan dit uitbouwen naar first-then-list e.d.
            # In deze skeleton-versie zijn groepen placeholders: we markeren
            # ze als meteen 'klaar'. Echte groep-semantiek komt terug zodra
            # de UI parent/child relaties netjes kan opslaan.
            r.action_duration = 0.0

        elif t == CueType.MEMO:
            r.action_duration = 0.0

        else:
            r.action_duration = 0.0

        # Auto-continue: volgende cue start wanneer de actie start
        if cue.continue_mode == ContinueMode.AUTO_CONTINUE:
            self._advance_and_go()

    def _advance_and_go(self) -> None:
        """Start de volgende cue in de lijst (voor auto-continue/auto-follow)."""
        if self._playhead_index >= len(self.workspace.cues):
            return
        nxt = self.workspace.cues[self._playhead_index]
        self._playhead_index += 1
        self._start_cue(nxt)

    def _stop_running(self, cue_id: str, finished: bool) -> None:
        r = self._running.pop(cue_id, None)
        if r is None:
            return
        r.cue.state = "finished" if finished else "idle"
        self.cue_state_changed.emit(r.cue.id)
        self.running_changed.emit()

    # ---- tick --------------------------------------------------------------

    def _tick(self) -> None:
        now = time.monotonic()
        to_advance: list[str] = []

        for cid, r in list(self._running.items()):
            elapsed_phase = now - r.phase_started_at

            if r.phase == "pre_wait":
                if elapsed_phase >= r.cue.pre_wait:
                    self._begin_action(r)

            elif r.phase == "action":
                finished = False
                if r.cue.cue_type == CueType.AUDIO:
                    if r.action_duration > 0:
                        if elapsed_phase >= r.action_duration:
                            finished = True
                    else:
                        if not self.audio.is_playing(r.cue.id):
                            finished = True
                else:
                    if elapsed_phase >= r.action_duration:
                        finished = True

                if finished:
                    r.phase = "post_wait"
                    r.phase_started_at = now
                    # Auto-follow: volgende cue start ná de actie
                    if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW:
                        to_advance.append(cid)
                    # Audio engine cleanup
                    if r.cue.cue_type == CueType.AUDIO:
                        self.audio.stop_cue(r.cue.id)

            elif r.phase == "post_wait":
                if elapsed_phase >= r.cue.post_wait:
                    self._stop_running(cid, finished=True)

        for _cid in to_advance:
            self._advance_and_go()
