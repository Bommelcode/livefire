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
    AudioEngine, DmxEngine, ImageEngine, OscInputEngine, OscOutputEngine,
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
    # True wanneer deze cue als child van een first-then-list-group
    # gevuurd is. In dat geval triggert z'n eigen continue_mode niet
    # _advance_and_go (de globale playhead is al voorbij de group),
    # maar wordt de chain gedraaid door _advance_group_chain.
    in_group_chain: bool = False


class PlaybackController(QObject):
    """Bezit de engines en rijdt de cue-lijst af wanneer de gebruiker GO
    indrukt. Signals laten de UI statuschanges tonen."""

    cue_state_changed = pyqtSignal(str)   # cue.id
    running_changed = pyqtSignal()
    # Playhead-positie is gewijzigd. Wordt geëmit zodra de controller-
    # interne playhead beweegt — bv. via een OSC-command zoals
    # /livefire/playhead/next. UI luistert hierop om de cuelist visueel
    # te syncen. Niet geëmit door go() omdat MainWindow.action_go z'n
    # eigen sync-pad heeft (en we anders een loop met cuelist krijgen).
    playhead_changed = pyqtSignal(int)
    # Companion-module vraagt om een verse cuelist-snapshot via
    # /livefire/snapshot/please (zie _handle_livefire_command). MainWindow
    # luistert hier en duwt _broadcast_cuelist_snapshot.
    snapshot_requested = pyqtSignal()
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
        dmx: DmxEngine | None = None,
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
        self.dmx = dmx if dmx is not None else DmxEngine(self)
        self.dmx.start()

        self._running: dict[str, _Running] = {}
        self._playhead_index: int = 0
        # Group-chain bookkeeping voor first-then-list-mode: per group-id
        # een lijst van nog-te-vuren children, en een reverse-lookup
        # (child-id → group-id) zodat _stop_running de keten kan
        # doorzetten zodra een child klaar is.
        self._group_chain: dict[str, list[Cue]] = {}
        self._group_chain_owner: dict[str, str] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- workspace management ---------------------------------------------

    def set_workspace(self, ws: Workspace) -> None:
        self.stop_all()
        self.workspace = ws
        self._playhead_index = 0
        # Pre-decode alle audio-bestanden in de achtergrond, zodat fire = 0ms
        # disk + decode latency. Bij grote workspaces wordt dit verspreid
        # over de threads die preload() spawnt — geen UI-block.
        for cue in ws.cues:
            if cue.cue_type == CueType.AUDIO and cue.file_path:
                self.audio.preload(cue.file_path)

    def shutdown(self) -> None:
        self._timer.stop()
        self.stop_all()
        self.audio.stop()
        self.osc.stop()
        self.osc_out.shutdown()
        self.video.shutdown()
        self.image.shutdown()
        self.powerpoint.shutdown()
        self.dmx.shutdown()

    # ---- transport ---------------------------------------------------------

    @property
    def playhead_index(self) -> int:
        return self._playhead_index

    def set_playhead(self, index: int) -> None:
        new_idx = max(0, min(index, len(self.workspace.cues)))
        if new_idx == self._playhead_index:
            return
        self._playhead_index = new_idx
        self.playhead_changed.emit(self._playhead_index)

    def go(self) -> None:
        """Start de cue op de playhead, schuif playhead door."""
        if self._playhead_index >= len(self.workspace.cues):
            return
        cue = self.workspace.cues[self._playhead_index]
        self._playhead_index += 1
        # UI moet weten dat de playhead bewogen is — anders blijft de
        # oranje highlight op de oude rij staan wanneer go() via een
        # extern pad (OSC, Stream Deck) wordt getriggerd. action_go in
        # MainWindow bewerkt de cuelist al expliciet, dus voor het
        # keyboard/menu-pad is dit een no-op (idempotent in cuelist).
        self.playhead_changed.emit(self._playhead_index)
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
        info = self._primary_running_info()
        if info is None:
            return None
        return (info["label"], info["seconds"], info["is_countdown"])

    def primary_elapsed(self) -> float | None:
        """Elapsed-tijd in seconden van dezelfde cue die ``primary_countdown``
        drijft. Bij een aftellende audio-cue groeit deze van 0 → duration;
        bij een oneindige loop groeit 'ie ongebonden door."""
        info = self._primary_running_info()
        if info is None:
            return None
        return info["elapsed"]

    def _primary_running_info(self) -> dict | None:
        """Gedeelde helper voor primary_countdown en primary_elapsed.
        Retourneert ``{label, seconds, is_countdown, elapsed}`` voor de
        cue die de transport-display drijft, of None."""
        best: dict | None = None
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
                    best = {
                        "label": label, "seconds": remaining,
                        "is_countdown": True, "elapsed": elapsed,
                    }
            else:
                src_remaining = self.audio.get_remaining(r.cue.id)
                if src_remaining is None:
                    continue
                if src_remaining < 0:
                    # Oneindige loop — count-up
                    if elapsed > best_remaining:
                        best_remaining = elapsed
                        best = {
                            "label": label, "seconds": elapsed,
                            "is_countdown": False, "elapsed": elapsed,
                        }
                else:
                    if src_remaining > best_remaining:
                        best_remaining = src_remaining
                        best = {
                            "label": label, "seconds": src_remaining,
                            "is_countdown": True, "elapsed": elapsed,
                        }
        return best

    # ---- trigger-matching --------------------------------------------------

    def _on_osc_message(self, address: str, args: tuple) -> None:
        """Inkomende OSC heeft twee handlers:

        1. **Built-in transport-commands** (``/livefire/...``) — voor
           Companion-integratie en handmatige OSC-tests. GO / Stop All /
           playhead-control / fire-by-number.
        2. **Per-cue trigger_osc** — legacy pad: een cue vuurt zichzelf
           als z'n eigen ``trigger_osc``-veld matcht.

        Beide paden draaien naast elkaar zodat een gebruiker die de
        oude aanpak (één unique address per cue) gebruikt niets merkt
        van de nieuwe Companion-API.
        """
        if address.startswith("/livefire/"):
            self._handle_livefire_command(address, args)
        for cue in self.workspace.cues:
            if cue.trigger_osc and cue.trigger_osc == address:
                self.fire_cue(cue.id)

    def _handle_livefire_command(self, address: str, args: tuple) -> None:
        """Router voor de Companion/integratie-API. Onbekende addresses
        in de ``/livefire/...``-namespace worden stilzwijgend genegeerd
        — Companion verzendt soms heartbeat-pings die we niet kennen."""
        if address == "/livefire/go":
            self.go()
            return
        if address == "/livefire/stop_all":
            self.stop_all()
            return
        if address == "/livefire/playhead/next":
            self.set_playhead(self._playhead_index + 1)
            return
        if address == "/livefire/playhead/prev":
            self.set_playhead(self._playhead_index - 1)
            return
        if address == "/livefire/playhead/goto":
            if args and isinstance(args[0], (int, float)):
                self.set_playhead(int(args[0]))
            return
        if address == "/livefire/snapshot/please":
            # Companion vraagt na (re)connect een verse snapshot van de
            # hele cuelist. We laten 't aan MainWindow over via 't signal
            # zodat de controller niet hoeft te weten van OscFeedback.
            self.snapshot_requested.emit()
            return
        # /livefire/fire/<cue_number> — match op cue.cue_number (vrij
        # tekstveld; we vergelijken case-sensitive).
        prefix = "/livefire/fire/"
        if address.startswith(prefix):
            target_number = address[len(prefix):]
            if not target_number:
                return
            for cue in self.workspace.cues:
                if cue.cue_number == target_number:
                    self.fire_cue(cue.id)
                    return
            return

    def stop_all(self) -> None:
        ids = list(self._running.keys())
        for cid in ids:
            self._stop_running(cid, finished=False)
        # Reset group-chain bookkeeping zodat een eventuele lopende
        # first-then-list niet ineens herstart als een nieuwe Group-cue
        # straks dezelfde id krijgt (zou niet gebeuren met UUIDs maar
        # explicit > implicit).
        self._group_chain.clear()
        self._group_chain_owner.clear()
        self.audio.stop_all()
        self.video.stop_all()
        self.image.stop_all()
        # Sluit ook een lopende PowerPoint-slideshow zodat Esc / Stop All
        # alle visuele output dichtklapt — anders blijft het PowerPoint-
        # window over de cuelist hangen tot een Close-cue. Veilig om te
        # roepen ook als er geen presentatie open is.
        self.powerpoint.close()
        # DMX-blackout op Stop All: alle universes naar 0 zodat lichten
        # uitgaan bij paniek. Een lichttafel-style cue-stop laat
        # waardes anders staan, wat tijdens een show fout kan voelen.
        self.dmx.blackout()

    def stop_cue(self, cue_id: str) -> None:
        # Group-cue → cascade naar alle nakomelingen (recursief). Doe
        # dat eerst zodat de chain-keten netjes leeg is voordat we de
        # group zelf stoppen.
        cue = self.workspace.find(cue_id)
        if cue is not None and cue.cue_type == CueType.GROUP:
            self._group_chain.pop(cue_id, None)
            for descendant in self.workspace.descendants_of(cue_id):
                self._group_chain_owner.pop(descendant.id, None)
                self.stop_cue(descendant.id)  # recursief — neemt nested groups mee
        if cue_id in self._running:
            self._stop_running(cue_id, finished=False)
        self.audio.stop_cue(cue_id)
        self.video.stop_cue(cue_id)
        self.image.stop_cue(cue_id)
        self.dmx.stop_cue(cue_id)

    # ---- cue-specifieke start-logica --------------------------------------

    def _start_cue(self, cue: Cue, in_group_chain: bool = False) -> None:
        now = time.monotonic()
        running = _Running(cue=cue, started_at=now, phase="pre_wait",
                           phase_started_at=now,
                           in_group_chain=in_group_chain)
        self._running[cue.id] = running
        cue.state = "running"
        self.cue_state_changed.emit(cue.id)
        self.running_changed.emit()
        # pre_wait=0 (default): meteen doorschieten naar action zodat we
        # niet tot de volgende _tick wachten — dat scheelt 0-20 ms tussen
        # GO en hoorbaar audio. Voor pre_wait>0 laten we _tick het pad
        # nemen, dan klopt de timing met monotonic() exact.
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
            # de hele chain breekt — behalve voor children van een
            # first-then-list-group; daar regelt _advance_group_chain.
            if cue.continue_mode == ContinueMode.AUTO_CONTINUE and not r.in_group_chain:
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

        elif t == CueType.DMX:
            ok, err = self.dmx.play(cue)
            if not ok:
                # Net als bij Network: surface in de statusbar via de
                # network_send_failed-signal (dezelfde UI-handler is
                # bruikbaar — toont een transiente waarschuwing).
                self.network_send_failed.emit(cue.id, f"DMX: {err}")
                r.action_duration = 0.0
            elif cue.dmx_mode == "fade":
                r.action_duration = max(0.0, float(cue.dmx_fade_time))
            elif cue.dmx_mode == "chase":
                # Eindigt na chase_loops_total × step_time × steps; bij 0 →
                # oneindig (cue blijft "running" tot Stop). Voor 0 zetten
                # we duration op 0 zodat AUTO_FOLLOW direct doorpakt; de
                # operator stopt 'm dan handmatig met een Stop-cue.
                steps = max(1, len([s for s in cue.dmx_chase_steps.split("|") if s.strip()]))
                if cue.dmx_chase_loops > 0:
                    cycle = (
                        2 * (steps - 1) if (cue.dmx_chase_pingpong and steps > 1)
                        else steps
                    )
                    r.action_duration = (
                        cue.dmx_chase_loops * cycle * cue.dmx_step_time
                    )
                else:
                    r.action_duration = 0.0
            else:
                # snapshot — instant, blijft als state in de buffer staan.
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
            r.action_duration = self._fire_group(cue)

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

        # Auto-continue: volgende cue start wanneer de actie start.
        # Onderdrukt voor children van een first-then-list-group: hun
        # eigen continue_mode mag de globale playhead niet doorduwen
        # voorbij de group, want de group heeft de playhead al na zichzelf
        # geplaatst en wij chaiñen de children intern via _group_chain.
        if cue.continue_mode == ContinueMode.AUTO_CONTINUE and not r.in_group_chain:
            self._advance_and_go()

    def _advance_and_go(self) -> None:
        """Start de volgende cue in de lijst (voor auto-continue/auto-follow)."""
        if self._playhead_index >= len(self.workspace.cues):
            return
        nxt = self.workspace.cues[self._playhead_index]
        self._playhead_index += 1
        # Sync UI — zelfde reden als go(): zonder emit blijft de oranje
        # highlight op de vorige rij staan tijdens AUTO_CONTINUE/AUTO_FOLLOW.
        self.playhead_changed.emit(self._playhead_index)
        self._start_cue(nxt)

    # ---- group-cue afhandeling --------------------------------------------

    def _fire_group(self, cue: Cue) -> float:
        """Vuur een Group-cue af volgens z'n group_mode.

        Returns de ``action_duration`` voor de _Running entry — typisch 0
        omdat de child-cues hun eigen lifecycle hebben.

        * ``list``            — playhead stapt naar de eerste child zonder
                                te vuren. Operator GO't de children
                                handmatig één voor één.
        * ``first-then-list`` — vuurt children sequentieel; iedere child
                                krijgt impliciet AUTO_CONTINUE-gedrag tot
                                de laatste. Playhead skipt voorbij de
                                hele group-block.
        * ``parallel``        — vuurt alle children tegelijk; playhead
                                skipt voorbij de group-block.
        * ``random``          — vuurt één willekeurige child; playhead
                                skipt voorbij de group-block.
        """
        children = self.workspace.children_of(cue.id)
        if not children:
            return 0.0

        mode = cue.group_mode or "list"

        if mode == "list":
            # Zet playhead op de eerste child zonder hem te vuren. Het
            # standaard tick-pad voor AUTO_CONTINUE / AUTO_FOLLOW raakt
            # de group zelf niet (we hebben r.action_duration = 0 +
            # geen audio engine = direct in post_wait), dus de playhead
            # wijst nu naar de eerste child en de operator kan z'n
            # volgende GO doen.
            first = children[0]
            child_idx = self.workspace.index_of(first.id)
            if child_idx >= 0:
                self.set_playhead(child_idx)
            return 0.0

        # Voor de niet-list-modes: playhead skipt voorbij de group + alle
        # nakomelingen, anders zou de volgende GO een child opnieuw
        # afvuren die we al van plan waren te firen.
        end_idx = self.workspace.first_index_after_group(cue.id)
        self.set_playhead(end_idx)

        if mode == "parallel":
            for child in children:
                self._start_cue(child)
            return 0.0

        if mode == "random":
            import random
            choice = random.choice(children)
            self._start_cue(choice)
            return 0.0

        # mode == "first-then-list" — sequentieel. We registreren een
        # auto-chain-marker op de _Running van het eerste child zodat
        # _stop_running 't volgende child kan starten zodra de huidige
        # klaar is. Dit werkt door iedere child impliciet als AUTO_FOLLOW
        # te behandelen via het _group_chain-state.
        self._group_chain[cue.id] = list(children)
        first = children[0]
        self._group_chain_owner[first.id] = cue.id
        # in_group_chain=True onderdrukt de eigen continue_mode van het
        # child zodat 't niet dubbel de globale playhead doorduwt.
        self._start_cue(first, in_group_chain=True)
        return 0.0

    def _advance_group_chain(self, finished_child_id: str) -> None:
        """Wordt door _stop_running aangeroepen wanneer een child uit een
        first-then-list-group klaar is. Vuur het volgende child."""
        group_id = self._group_chain_owner.pop(finished_child_id, None)
        if group_id is None:
            return
        chain = self._group_chain.get(group_id)
        if not chain:
            return
        # Verwijder finished child uit de keten.
        chain[:] = [c for c in chain if c.id != finished_child_id]
        if not chain:
            self._group_chain.pop(group_id, None)
            return
        nxt = chain[0]
        self._group_chain_owner[nxt.id] = group_id
        self._start_cue(nxt, in_group_chain=True)

    def _stop_running(self, cue_id: str, finished: bool) -> None:
        r = self._running.pop(cue_id, None)
        if r is None:
            return
        r.cue.state = "finished" if finished else "idle"
        self.cue_state_changed.emit(r.cue.id)
        self.running_changed.emit()
        # Als deze cue onderdeel was van een first-then-list-chain, vuur
        # de volgende child af. Doe dit alleen bij ``finished`` — een
        # handmatige stop midden in een group hoort niet de rest van de
        # chain alsnog te triggeren.
        if finished and cue_id in self._group_chain_owner:
            self._advance_group_chain(cue_id)

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
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW and not r.in_group_chain:
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
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW and not r.in_group_chain:
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
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW and not r.in_group_chain:
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
                            if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW and not r.in_group_chain:
                                to_advance.append(cid)
                            if r.cue.image_fade_out <= 0:
                                finished = True
                        elif r.stop_triggered:
                            if not self.image.is_playing(r.cue.id):
                                finished = True
                    else:
                        if elapsed_phase >= r.action_duration:
                            finished = True
                            if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW and not r.in_group_chain:
                                to_advance.append(cid)
                else:
                    if elapsed_phase >= r.action_duration:
                        finished = True
                        # Niet-audio/video: AUTO_FOLLOW triggert hier.
                        if r.cue.continue_mode == ContinueMode.AUTO_FOLLOW and not r.in_group_chain:
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
