"""Playback controller. Orchestreert GO-acties, pre/post-waits,
continue-modes en stuurt cues door naar de juiste engines.

Draait op de Qt-hoofdthread; gebruikt een QTimer voor ticks zodat we
consistent zijn met de rest van de app. De audio-engine heeft z'n eigen
thread (PortAudio callback) maar die raken we hier alleen via zijn API."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..cues import Cue, CueType, ContinueMode, PresentationAction
from ..engines import (
    AudioEngine, ImageEngine, OscInputEngine, OscOutputEngine,
    PowerPointEngine, VideoEngine,
)
from ..engines.osc_out import parse_args as parse_osc_args
from ..workspace import Workspace
from .. import licensing


TICK_MS = 20  # 50 Hz tick — ruim voldoende voor cue-timing, voor audio doet
               # de PortAudio callback het sample-accurate werk.


@dataclass
class _Running:
    cue: Cue
    started_at: float
    phase: str = "pre_wait"   # pre_wait | action | post_wait | done
    phase_started_at: float = 0.0
    action_duration: float = 0.0   # berekend op moment van action-start
    stop_triggered: bool = False   # voor audio: fade-out al ingezet?


class PlaybackController(QObject):
    """Bezit de engines en rijdt de cue-lijst af wanneer de gebruiker GO
    indrukt. Signals laten de UI statuschanges tonen."""

    cue_state_changed = pyqtSignal(str)   # cue.id
    running_changed = pyqtSignal()
    # Wanneer een Network-cue's OSC-send faalt (lege/ongeldige address,
    # python-osc niet beschikbaar, enz.), emit (cue_id, error_message).
    # De UI kan zich hieraan abonneren om de operator te waarschuwen.
    network_send_failed = pyqtSignal(str, str)
    # Wanneer een cue NIET wordt afgespeeld omdat de licentie het cue-type
    # niet ondersteunt (Pro-feature in FREE-tier). De UI flash't dit in
    # de statusbar en de show gaat door naar post_wait.
    cue_blocked_by_license = pyqtSignal(str, str)  # cue_id, cue_type
    network_send_failed = pyqtSignal(str, str)  # cue_id, error_message — voor UI-statusbar

    def __init__(
        self,
        workspace: Workspace,
        parent: QObject | None = None,
        audio: AudioEngine | None = None,
        osc: OscInputEngine | None = None,
        video: VideoEngine | None = None,
        powerpoint: PowerPointEngine | None = None,
        image: ImageEngine | None = None,
        osc_out: OscOutputEngine | None = None,
    ):
        super().__init__(parent)
        self.workspace = workspace
        self.audio = audio if audio is not None else AudioEngine()
        self.audio.start()

        self.osc = osc if osc is not None else OscInputEngine(self)
        self.osc.message_received.connect(self._on_osc_message)

        self.video = video if video is not None else VideoEngine(self)
        self.powerpoint = powerpoint if powerpoint is not None else PowerPointEngine(self)
        self.image = image if image is not None else ImageEngine(self)
        self.osc_out = osc_out if osc_out is not None else OscOutputEngine(self)

        self._running: dict[str, _Running] = {}
        self._playhead_index: int = 0

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Preload audio-files uit een workspace die al gevuld is bij
        # constructie (bv. een geladen .livefire bij app-start).
        self._preload_audio_cues()

    # ---- workspace management ---------------------------------------------

    def set_workspace(self, ws: Workspace) -> None:
        self.stop_all()
        self.workspace = ws
        self._playhead_index = 0
        self._preload_audio_cues()

    def _preload_audio_cues(self) -> None:
        """Trigger async-preload van alle audio-cues in de huidige
        workspace, zodat de eerste GO geen disk-IO doet (een 5-min WAV
        kan synchroon makkelijk een seconde kosten op de hoofdthread).
        Veilig om te roepen als audio-engine niet beschikbaar is — de
        preload-call test dat zelf en geeft False zonder error."""
        if not getattr(self.audio, "available", False):
            return
        for cue in self.workspace.cues:
            if cue.cue_type == CueType.AUDIO and cue.file_path:
                self.audio.preload_async(cue.file_path)

    def shutdown(self) -> None:
        self._timer.stop()
        self.stop_all()
        self.audio.stop()
        self.osc.stop()
        self.osc_out.shutdown()
        self.video.shutdown()
        self.image.shutdown()
        self.powerpoint.shutdown()

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

    def fire_cue(self, cue_id: str) -> bool:
        """Start een specifieke cue zonder de playhead te verplaatsen
        (voor externe triggers zoals OSC/MIDI)."""
        cue = self.workspace.find(cue_id)
        if cue is None:
            return False
        self._start_cue(cue)
        return True

    def primary_countdown(self) -> tuple[str, float, bool] | None:
        """Info voor de grote countdown-label in de transportbalk.

        Retourneert ``(label, seconds, is_countdown)`` of ``None``:
        - ``is_countdown=True`` → seconds telt af (resterend)
        - ``is_countdown=False`` → seconds telt op (bv. bij oneindige loop)

        Pakt de audio-cue in 'action'-fase met de grootste resterende tijd.
        """
        best: tuple[str, float, bool] | None = None
        best_remaining = -1.0
        for r in self._running.values():
            if r.phase != "action":
                continue
            if r.cue.cue_type != CueType.AUDIO:
                continue
            elapsed = time.monotonic() - r.phase_started_at
            label = r.cue.name or "(naamloos)"
            if r.action_duration > 0:
                remaining = max(0.0, r.action_duration - elapsed)
                if remaining > best_remaining:
                    best_remaining = remaining
                    best = (label, remaining, True)
            else:
                src_remaining = self.audio.get_remaining(r.cue.id)
                if src_remaining is None:
                    continue
                if src_remaining < 0:
                    # Oneindige loop — count-up
                    if elapsed > best_remaining:
                        best_remaining = elapsed
                        best = (label, elapsed, False)
                else:
                    if src_remaining > best_remaining:
                        best_remaining = src_remaining
                        best = (label, src_remaining, True)
        return best

    # ---- trigger-matching --------------------------------------------------

    def _on_osc_message(self, address: str, _args: tuple) -> None:
        """Op inkomende OSC: vind cues met trigger_osc == address en vuur ze."""
        for cue in self.workspace.cues:
            if cue.trigger_osc and cue.trigger_osc == address:
                self.fire_cue(cue.id)

    def stop_all(self) -> None:
        ids = list(self._running.keys())
        for cid in ids:
            self._stop_running(cid, finished=False)
        self.audio.stop_all()
        self.video.stop_all()
        self.image.stop_all()
        # Sluit ook een lopende PowerPoint-slideshow zodat Esc / Stop All
        # alle visuele output dichtklapt — anders blijft het PowerPoint-
        # window over de cuelist hangen tot een Close-cue. Veilig om te
        # roepen ook als er geen presentatie open is.
        self.powerpoint.close()

    def stop_cue(self, cue_id: str) -> None:
        if cue_id in self._running:
            self._stop_running(cue_id, finished=False)
        self.audio.stop_cue(cue_id)
        self.video.stop_cue(cue_id)
        self.image.stop_cue(cue_id)

    # ---- cue-specifieke start-logica --------------------------------------

    def _start_cue(self, cue: Cue) -> None:
        now = time.monotonic()
        running = _Running(cue=cue, started_at=now, phase="pre_wait",
                           phase_started_at=now)
        self._running[cue.id] = running
        cue.state = "running"
        self.cue_state_changed.emit(cue.id)
        self.running_changed.emit()
        # Bij pre_wait=0 (default voor de meeste cues) starten we de
        # actie meteen in plaats van een tick (20 ms) te wachten — dat
        # scheelt waarneembaar veel bij OSC-getriggerde cues. Bij
        # pre_wait > 0 wacht _tick netjes af.
        if cue.pre_wait <= 0:
            self._begin_action(running)

    def _begin_action(self, r: _Running) -> None:
        cue = r.cue
        r.phase = "action"
        r.phase_started_at = time.monotonic()

        # Licensing-gate: vergrendelde cue-types vuren niet bij GO. We
        # houden de cue-lifecycle wel intact (post_wait + AUTO_FOLLOW)
        # zodat de show-flow niet kapotgaat — alleen de actie wordt
        # overgeslagen en een signal informeert de UI.
        if not licensing.has_feature(cue.cue_type):
            self.cue_blocked_by_license.emit(cue.id, cue.cue_type)
            r.action_duration = 0.0
            # AUTO_CONTINUE moet ook nog werken zodat een blokkade niet
            # de hele chain breekt.
            if cue.continue_mode == ContinueMode.AUTO_CONTINUE:
                self._advance_and_go()
            return

        t = cue.cue_type
        if t == CueType.AUDIO:
            ok = self.audio.play_file(
                cue_id=cue.id,
                file_path=cue.file_path,
                volume_db=cue.volume_db,
                loops=cue.loops,
                start_offset=cue.audio_start_offset,
                end_offset=cue.audio_end_offset,
                fade_in=cue.audio_fade_in,
            )
            if not ok:
                r.action_duration = 0.0
            else:
                r.action_duration = cue.duration if cue.duration > 0 else 0.0
                # 0 = laten lopen tot bestand op is (detecteren via audio.is_playing)

        elif t == CueType.VIDEO:
            ok, _err = self.video.play_file(
                cue_id=cue.id,
                file_path=cue.file_path,
                screen_index=cue.video_output_screen,
                fade_in=cue.video_fade_in,
                fade_out=cue.video_fade_out,
                start_offset=cue.video_start_offset,
                end_offset=cue.video_end_offset,
                volume_db=cue.volume_db,
                hold_last_frame=cue.video_last_frame_store,
            )
            if not ok:
                r.action_duration = 0.0
            else:
                r.action_duration = cue.duration if cue.duration > 0 else 0.0

        elif t == CueType.PRESENTATION:
            action = cue.presentation_action
            if action == PresentationAction.OPEN:
                self.powerpoint.open(cue.file_path)
            elif action == PresentationAction.NEXT:
                self.powerpoint.next_slide()
            elif action == PresentationAction.PREVIOUS:
                self.powerpoint.previous_slide()
            elif action == PresentationAction.GOTO:
                self.powerpoint.goto_slide(cue.presentation_slide)
            elif action == PresentationAction.CLOSE:
                self.powerpoint.close()
            r.action_duration = 0.0

        elif t == CueType.IMAGE:
            ok, _err = self.image.play(
                cue_id=cue.id,
                file_path=cue.file_path,
                screen_index=cue.image_output_screen,
                fade_in=cue.image_fade_in,
                fade_out=cue.image_fade_out,
                duration=cue.duration,
            )
            if not ok:
                r.action_duration = 0.0
            else:
                # duration > 0 → engine sluit zichzelf af na duration sec.
                # duration == 0 → image blijft staan; cue is "klaar" zodra
                # de fade-in voltooid is, zodat AUTO_FOLLOW kan chainen.
                if cue.duration > 0:
                    r.action_duration = cue.duration
                else:
                    r.action_duration = max(cue.image_fade_in, 0.0)

        elif t == CueType.NETWORK:
            args = parse_osc_args(cue.network_args)
            ok, err = self.osc_out.send(
                cue.network_host, cue.network_port,
                cue.network_address, args,
            )
            if not ok:
                # Surface naar de UI zodat de statusbar het kan tonen —
                # anders weet de operator niet dat de OSC-trigger niet
                # is aangekomen.
                self.network_send_failed.emit(cue.id, err)
            # Network-cues zijn instant: het verzenden gebeurt synchroon.
            r.action_duration = 0.0

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

        # AUTO_FOLLOW + volgende cue is een Video → preload 'm vast zodat de
        # transitie straks naadloos is (libVLC heeft het eerste frame al
        # gedecodeerd voor we 'm tonen).
        if cue.continue_mode == ContinueMode.AUTO_FOLLOW:
            if self._playhead_index < len(self.workspace.cues):
                nxt = self.workspace.cues[self._playhead_index]
                if nxt.cue_type == CueType.VIDEO and nxt.file_path:
                    self.video.preload(
                        cue_id=nxt.id,
                        file_path=nxt.file_path,
                        screen_index=nxt.video_output_screen,
                        fade_out=nxt.video_fade_out,
                        start_offset=nxt.video_start_offset,
                        end_offset=nxt.video_end_offset,
                        volume_db=nxt.volume_db,
                    )

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
                    # Bepaal wanneer de "main playback" eindigt (expliciete
                    # duration óf natuurlijk einde van het bestand).
                    main_done = False
                    if r.action_duration > 0:
                        if elapsed_phase >= r.action_duration:
                            main_done = True
                    else:
                        if not self.audio.is_playing(r.cue.id):
                            main_done = True

                    if main_done and not r.stop_triggered:
                        self.audio.stop_cue(r.cue.id, fade_out=r.cue.audio_fade_out)
                        r.stop_triggered = True
                        # AUTO_FOLLOW moet hier al triggeren zodat de volgende
                        # cue start terwijl deze uitfadet — dat geeft de
                        # gewenste crossfade.
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW:
                            to_advance.append(cid)
                        if r.cue.audio_fade_out <= 0:
                            finished = True
                    elif r.stop_triggered:
                        # Wacht tot fade-out klaar is voor we post_wait ingaan.
                        if not self.audio.is_playing(r.cue.id):
                            finished = True
                elif r.cue.cue_type == CueType.VIDEO:
                    # Zelfde patroon als audio: duration > 0 of natuurlijk einde,
                    # daarna fade-out (zit al in video-engine via stored fade_out_s).
                    main_done = False
                    if r.action_duration > 0:
                        if elapsed_phase >= r.action_duration:
                            main_done = True
                    else:
                        if not self.video.is_playing(r.cue.id):
                            main_done = True

                    if main_done and not r.stop_triggered:
                        self.video.stop_cue(r.cue.id, fade_out=r.cue.video_fade_out)
                        r.stop_triggered = True
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW:
                            to_advance.append(cid)
                        if r.cue.video_fade_out <= 0:
                            finished = True
                    elif r.stop_triggered:
                        if not self.video.is_playing(r.cue.id):
                            finished = True
                elif (r.cue.cue_type == CueType.PRESENTATION
                      and r.cue.presentation_action == PresentationAction.OPEN):
                    # Wacht tot de slideshow klaar is (laatste slide gepasseerd
                    # of user drukte ESC) voordat AUTO_FOLLOW de volgende
                    # cue afvuurt. Sluit dan ook de presentatie zelf, anders
                    # blijft de zwarte "klik om af te sluiten"-slide of de
                    # PowerPoint-editor over onze UI staan.
                    if not self.powerpoint.is_slideshow_active():
                        finished = True
                        self.powerpoint.close()
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW:
                            to_advance.append(cid)
                elif r.cue.cue_type == CueType.IMAGE:
                    # duration > 0: net als video — wacht op de duration en
                    # initieer dan de fade-out via de engine.
                    # duration == 0: cue is klaar zodra de fade-in voltooid is
                    # (action_duration == fade_in seconden); de image-window
                    # blijft staan tot vervangen door een volgende image-cue
                    # of een Stop-cue.
                    if r.cue.duration > 0:
                        if elapsed_phase >= r.action_duration and not r.stop_triggered:
                            self.image.stop_cue(r.cue.id, fade_out=r.cue.image_fade_out)
                            r.stop_triggered = True
                            if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW:
                                to_advance.append(cid)
                            if r.cue.image_fade_out <= 0:
                                finished = True
                        elif r.stop_triggered:
                            if not self.image.is_playing(r.cue.id):
                                finished = True
                    else:
                        if elapsed_phase >= r.action_duration:
                            finished = True
                            if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW:
                                to_advance.append(cid)
                else:
                    if elapsed_phase >= r.action_duration:
                        finished = True
                        # Niet-audio/video: AUTO_FOLLOW triggert hier.
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW:
                            to_advance.append(cid)

                if finished:
                    r.phase = "post_wait"
                    r.phase_started_at = now
                    # Zorg dat er niets blijft hangen.
                    if r.cue.cue_type == CueType.AUDIO:
                        self.audio.stop_cue(r.cue.id)
                    elif r.cue.cue_type == CueType.VIDEO:
                        self.video.stop_cue(r.cue.id)

            elif r.phase == "post_wait":
                if elapsed_phase >= r.cue.post_wait:
                    self._stop_running(cid, finished=True)

        for _cid in to_advance:
            self._advance_and_go()
