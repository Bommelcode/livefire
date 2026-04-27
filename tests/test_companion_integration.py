"""Tests voor de Companion-integratie (Phase 1):

* OscFeedbackEngine — periodieke + on-event push naar een ontvangende
  ThreadingOSCUDPServer.
* Controller's ``/livefire/...``-command-router — GO / Stop All /
  playhead-control / fire-by-number.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from livefire.cues import Cue, CueType
from livefire.engines.osc_feedback import OscFeedbackEngine
from livefire.workspace import Workspace


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- OscFeedbackEngine -----------------------------------------------------


class _Provider:
    """Snapshot-provider stub voor OscFeedbackEngine.

    Geeft een dict terug die de engine in periodieke OSC-pushes giet."""

    def __init__(self, snap: dict):
        self._snap = snap

    def snapshot(self) -> dict:
        return self._snap


def test_feedback_engine_pushes_periodic_snapshot(qt_app) -> None:
    try:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import ThreadingOSCUDPServer
    except ImportError:
        pytest.skip("python-osc niet geïnstalleerd")

    received: list[tuple[str, list]] = []
    ev = threading.Event()

    def collect(addr, *args):
        received.append((addr, list(args)))
        # Bevestig wanneer alle 5 verwachte addresses minstens 1× binnen zijn
        seen = {a for a, _ in received}
        if {"/livefire/playhead", "/livefire/active", "/livefire/remaining",
            "/livefire/remaining/label", "/livefire/countdown_active"} <= seen:
            ev.set()

    disp = Dispatcher()
    disp.set_default_handler(collect)
    port = _free_udp_port()
    server = ThreadingOSCUDPServer(("127.0.0.1", port), disp)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    eng = OscFeedbackEngine()
    eng.set_provider(_Provider({
        "playhead": 3,
        "playhead_total": 10,
        "playhead_name": "intro",
        "active": 2,
        "remaining": 12.5,
        "remaining_label": "intro music",
        "countdown_active": True,
    }))
    try:
        if not eng.available:
            pytest.skip("python-osc niet beschikbaar")
        ok, err = eng.start("127.0.0.1", port, interval_ms=20)
        assert ok, err
        # QTimer fires alleen als de Qt-event-loop pumped wordt; de test
        # heeft geen native loop, dus we pumpen 'm zelf totdat alle 5
        # adressen binnen zijn (of de deadline 'm vangt).
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not ev.is_set():
            qt_app.processEvents()
            time.sleep(0.01)
        assert ev.is_set(), "feedback-engine pusht niet alle bekende addresses"

        # Verifieer payload van /livefire/playhead
        playhead_msgs = [m for m in received if m[0] == "/livefire/playhead"]
        assert playhead_msgs, "geen /livefire/playhead ontvangen"
        addr, args = playhead_msgs[0]
        assert args == [3, 10, "intro"]

        active_msgs = [m for m in received if m[0] == "/livefire/active"]
        assert active_msgs and active_msgs[0][1] == [2]

        remaining_msgs = [m for m in received if m[0] == "/livefire/remaining"]
        assert remaining_msgs and abs(remaining_msgs[0][1][0] - 12.5) < 1e-6

        countdown_msgs = [m for m in received if m[0] == "/livefire/countdown_active"]
        assert countdown_msgs and countdown_msgs[0][1] == [1]
    finally:
        eng.shutdown()
        server.shutdown()
        server.server_close()
        th.join(timeout=1.0)


def test_feedback_engine_on_event_cue_state(qt_app) -> None:
    try:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import ThreadingOSCUDPServer
    except ImportError:
        pytest.skip("python-osc niet geïnstalleerd")

    received: list[tuple[str, list]] = []
    ev = threading.Event()

    def collect(addr, *args):
        received.append((addr, list(args)))
        if any(a == "/livefire/cue/7/state" for a, _ in received):
            ev.set()

    disp = Dispatcher()
    disp.set_default_handler(collect)
    port = _free_udp_port()
    server = ThreadingOSCUDPServer(("127.0.0.1", port), disp)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    eng = OscFeedbackEngine()
    try:
        if not eng.available:
            pytest.skip("python-osc niet beschikbaar")
        # Geen provider → geen periodieke push, alleen on-event.
        ok, err = eng.start("127.0.0.1", port, interval_ms=10000)
        assert ok, err

        eng.send_cue_state("7", "running")
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not ev.is_set():
            qt_app.processEvents()
            time.sleep(0.01)
        assert ev.is_set()

        msg = next(m for m in received if m[0] == "/livefire/cue/7/state")
        assert msg[1] == ["running"]
    finally:
        eng.shutdown()
        server.shutdown()
        server.server_close()
        th.join(timeout=1.0)


def test_feedback_engine_rejects_invalid_target() -> None:
    eng = OscFeedbackEngine()
    if not eng.available:
        pytest.skip("python-osc niet beschikbaar")
    ok, err = eng.start("", 1234)
    assert ok is False and "host" in err.lower()
    ok, err = eng.start("127.0.0.1", 0)
    assert ok is False and "port" in err.lower()


# ---- Controller-command-router --------------------------------------------


def _make_stub_controller(ws: Workspace):
    """Maak een PlaybackController-instance zonder de echte engines te
    starten. We patchen _start_cue zodat fire-by-number en go() observeerbaar
    zijn zonder audio-uitvoer."""
    from livefire.playback.controller import PlaybackController

    class _Stub(PlaybackController):
        def __init__(self, ws):
            from PyQt6.QtCore import QObject
            QObject.__init__(self)
            self.workspace = ws
            self._playhead_index = 0
            self._running = {}
            self.fired: list[str] = []

        def _start_cue(self, cue):  # type: ignore[override]
            self.fired.append(cue.id)

        def stop_all(self) -> None:  # type: ignore[override]
            self.fired.append("STOP_ALL")

    return _Stub(ws)


def test_router_go_advances_playhead_and_fires(qt_app) -> None:
    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number="1", name="a"))
    ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number="2", name="b"))
    ctrl = _make_stub_controller(ws)
    ctrl._handle_livefire_command("/livefire/go", ())
    assert ctrl.fired == [ws.cues[0].id]
    assert ctrl.playhead_index == 1


def test_router_stop_all(qt_app) -> None:
    ws = Workspace()
    ctrl = _make_stub_controller(ws)
    ctrl._handle_livefire_command("/livefire/stop_all", ())
    assert ctrl.fired == ["STOP_ALL"]


def test_router_playhead_next_prev_goto(qt_app) -> None:
    ws = Workspace()
    for i in range(5):
        ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number=str(i + 1), name=f"c{i}"))
    ctrl = _make_stub_controller(ws)

    ctrl._handle_livefire_command("/livefire/playhead/next", ())
    assert ctrl.playhead_index == 1
    ctrl._handle_livefire_command("/livefire/playhead/next", ())
    assert ctrl.playhead_index == 2
    ctrl._handle_livefire_command("/livefire/playhead/prev", ())
    assert ctrl.playhead_index == 1
    ctrl._handle_livefire_command("/livefire/playhead/goto", (4,))
    assert ctrl.playhead_index == 4
    # Goto buiten range → klemmen op grenzen
    ctrl._handle_livefire_command("/livefire/playhead/goto", (-3,))
    assert ctrl.playhead_index == 0
    ctrl._handle_livefire_command("/livefire/playhead/goto", (999,))
    assert ctrl.playhead_index == len(ws.cues)


def test_router_fire_by_cue_number(qt_app) -> None:
    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number="7", name="seven"))
    ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number="42", name="forty-two"))
    ctrl = _make_stub_controller(ws)

    ctrl._handle_livefire_command("/livefire/fire/42", ())
    assert ctrl.fired == [ws.cues[1].id]
    # Onbekend cue-nummer → geen actie
    ctrl._handle_livefire_command("/livefire/fire/999", ())
    assert ctrl.fired == [ws.cues[1].id]


def test_router_unknown_command_is_silent(qt_app) -> None:
    """Onbekende /livefire/...-addresses mogen niet crashen — Companion
    pingt soms heartbeats die we niet kennen."""
    ws = Workspace()
    ctrl = _make_stub_controller(ws)
    ctrl._handle_livefire_command("/livefire/heartbeat", ())
    ctrl._handle_livefire_command("/livefire/unknown/sub", (1, 2, 3))
    # Geen exceptions, geen fires.
    assert ctrl.fired == []


def test_set_playhead_emits_signal_only_on_change(qt_app) -> None:
    """controller.playhead_changed mag niet vuren als de waarde gelijk
    blijft — anders krijg je signaal-loops met de cuelist."""
    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number="1", name="a"))
    ctrl = _make_stub_controller(ws)
    emitted: list[int] = []
    ctrl.playhead_changed.connect(lambda i: emitted.append(i))

    ctrl.set_playhead(0)  # geen verandering
    assert emitted == []
    ctrl.set_playhead(1)
    assert emitted == [1]
    ctrl.set_playhead(1)  # geen verandering
    assert emitted == [1]
    ctrl.set_playhead(0)
    assert emitted == [1, 0]
