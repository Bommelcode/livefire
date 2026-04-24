"""Tests voor OscInputEngine en trigger-matching. We starten een echte
UDP-server op een vrije localhost-poort, sturen een OSC-message via
python-osc's UDP-client, en verifiëren dat het Qt-signal aangekomen is
en dat de matcher de juiste cue afvuurt."""

from __future__ import annotations

import socket
import time
from typing import List, Tuple

import pytest

from livefire.cues import Cue, CueType
from livefire.engines.osc import OscInputEngine
from livefire.workspace import Workspace


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_osc_engine_receives_message(qt_app):
    """Start de engine, stuur een OSC-message, verwacht dat message_received
    emit met (address, args)."""
    pytest.importorskip("pythonosc")
    from pythonosc.udp_client import SimpleUDPClient

    eng = OscInputEngine()
    port = _free_udp_port()
    ok, err = eng.start(port, host="127.0.0.1")
    assert ok, err

    received: List[Tuple[str, tuple]] = []
    eng.message_received.connect(lambda addr, args: received.append((addr, args)))

    try:
        client = SimpleUDPClient("127.0.0.1", port)
        client.send_message("/livefire/go/intro", [])

        # Wacht tot Qt-eventloop het signal heeft afgeleverd
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not received:
            qt_app.processEvents()
            time.sleep(0.02)
    finally:
        eng.stop()

    assert received, "geen OSC-message ontvangen"
    assert received[0][0] == "/livefire/go/intro"


def test_trigger_matcher_fires_matching_cue():
    """PlaybackController._on_osc_message moet cues met gelijke trigger_osc
    afvuren via fire_cue()."""
    # We mocken PlaybackController's dependency via Workspace + fire_cue stub.
    from livefire.playback.controller import PlaybackController

    class _Stub(PlaybackController):
        def __init__(self, ws):
            # Skip __init__ van echte controller (wil Qt + audio + osc).
            # We roepen QObject direct aan om de signals te vermijden.
            from PyQt6.QtCore import QObject
            QObject.__init__(self)
            self.workspace = ws
            self.fired: list[str] = []

        def fire_cue(self, cue_id: str) -> bool:  # type: ignore[override]
            self.fired.append(cue_id)
            return True

    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="a",
                   trigger_osc="/livefire/go/a"))
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="b",
                   trigger_osc="/livefire/go/b"))
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="c"))  # geen trigger

    ctrl = _Stub(ws)
    ctrl._on_osc_message("/livefire/go/b", ())

    assert ctrl.fired == [ws.cues[1].id]


def test_trigger_matcher_no_match_is_noop():
    from livefire.playback.controller import PlaybackController

    class _Stub(PlaybackController):
        def __init__(self, ws):
            from PyQt6.QtCore import QObject
            QObject.__init__(self)
            self.workspace = ws
            self.fired: list[str] = []

        def fire_cue(self, cue_id: str) -> bool:  # type: ignore[override]
            self.fired.append(cue_id)
            return True

    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="a",
                   trigger_osc="/livefire/go/a"))
    ctrl = _Stub(ws)
    ctrl._on_osc_message("/niet/bestaand", ())
    assert ctrl.fired == []


def test_trigger_matcher_ignores_empty_trigger():
    """Een cue zonder trigger_osc moet nooit matchen, ook niet met lege address."""
    from livefire.playback.controller import PlaybackController

    class _Stub(PlaybackController):
        def __init__(self, ws):
            from PyQt6.QtCore import QObject
            QObject.__init__(self)
            self.workspace = ws
            self.fired: list[str] = []

        def fire_cue(self, cue_id: str) -> bool:  # type: ignore[override]
            self.fired.append(cue_id)
            return True

    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="a"))  # trigger_osc=""
    ctrl = _Stub(ws)
    ctrl._on_osc_message("", ())
    assert ctrl.fired == []
