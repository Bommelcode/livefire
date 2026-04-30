"""Tests voor Network-cue (OSC-out) — v0.4.1.

Bevat:
- parse_args() — comma-separated, quoting, type-resolutie int/float/string
- OscOutputEngine.send() — input validation
- End-to-end: spin up een python-osc UDP-server in een thread, vuur een
  NETWORK-cue via de PlaybackController, assert dat de message arriveert.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest


# ---- parse_args ---------------------------------------------------------

def test_parse_args_empty() -> None:
    from livefire.engines.osc_out import parse_args
    assert parse_args("") == []
    assert parse_args("   ") == []


def test_parse_args_single_int() -> None:
    from livefire.engines.osc_out import parse_args
    assert parse_args("42") == [42]


def test_parse_args_single_float() -> None:
    from livefire.engines.osc_out import parse_args
    assert parse_args("0.5") == [0.5]


def test_parse_args_single_string() -> None:
    from livefire.engines.osc_out import parse_args
    assert parse_args("hello") == ["hello"]


def test_parse_args_mixed_types() -> None:
    from livefire.engines.osc_out import parse_args
    assert parse_args("channel, 1, 0.5") == ["channel", 1, 0.5]


def test_parse_args_double_quoted_string_with_spaces() -> None:
    from livefire.engines.osc_out import parse_args
    assert parse_args('"hello world", 42') == ["hello world", 42]


def test_parse_args_single_quoted_string_with_comma() -> None:
    """Een quoted string met komma's mag niet door de comma-splitter
    worden getokeniseerd."""
    from livefire.engines.osc_out import parse_args
    assert parse_args("'a, b, c', 1") == ["a, b, c", 1]


def test_parse_args_strips_whitespace() -> None:
    from livefire.engines.osc_out import parse_args
    assert parse_args("  1  ,   2  ,   3  ") == [1, 2, 3]


def test_parse_args_int_before_float() -> None:
    """'1' moet int worden, '1.0' moet float worden."""
    from livefire.engines.osc_out import parse_args
    out = parse_args("1, 1.0, 1e2")
    assert out[0] == 1 and isinstance(out[0], int)
    assert out[1] == 1.0 and isinstance(out[1], float)
    assert out[2] == 100.0 and isinstance(out[2], float)


def test_parse_args_quoted_number_stays_string() -> None:
    """Een gequote token moet altijd string blijven, ook als het er als
    getal uitziet — quoting is hoe je expliciet 'string' aangeeft."""
    from livefire.engines.osc_out import parse_args
    out = parse_args('"42"')
    assert out == ["42"]
    assert isinstance(out[0], str)
    out = parse_args('"3.14"')
    assert out == ["3.14"]
    assert isinstance(out[0], str)


def test_parse_args_quoted_whitespace_preserved() -> None:
    """Een gequote whitespace-token moet niet verloren gaan aan strip()."""
    from livefire.engines.osc_out import parse_args
    assert parse_args('" "') == [" "]
    assert parse_args('" ", "x"') == [" ", "x"]
    # Dubbele spaties binnen quote moeten ook intact blijven.
    assert parse_args('"  hello  "') == ["  hello  "]


def test_parse_args_mixed_quoted_and_unquoted() -> None:
    from livefire.engines.osc_out import parse_args
    out = parse_args('1, "hello", 0.5, "42"')
    assert out == [1, "hello", 0.5, "42"]
    assert isinstance(out[0], int)
    assert isinstance(out[1], str)
    assert isinstance(out[2], float)
    assert isinstance(out[3], str)  # "42" gequote → string


def test_parse_args_trailing_and_consecutive_commas() -> None:
    from livefire.engines.osc_out import parse_args
    # Trailing en lege tokens: niet-gequoot wordt geskipped na strip.
    assert parse_args("1,") == [1]
    assert parse_args("1,,2") == [1, 2]
    assert parse_args(", 1,") == [1]


# ---- OscOutputEngine input-validatie ------------------------------------

def test_engine_rejects_empty_address(qt_app) -> None:
    from livefire.engines.osc_out import OscOutputEngine
    eng = OscOutputEngine()
    if not eng.available:
        pytest.skip("python-osc niet geïnstalleerd")
    ok, err = eng.send("127.0.0.1", 53000, "", [])
    assert ok is False
    assert "address" in err.lower()


def test_engine_rejects_address_without_slash(qt_app) -> None:
    from livefire.engines.osc_out import OscOutputEngine
    eng = OscOutputEngine()
    if not eng.available:
        pytest.skip("python-osc niet geïnstalleerd")
    ok, err = eng.send("127.0.0.1", 53000, "noslash", [])
    assert ok is False
    assert "/" in err


def test_engine_rejects_invalid_port(qt_app) -> None:
    from livefire.engines.osc_out import OscOutputEngine
    eng = OscOutputEngine()
    if not eng.available:
        pytest.skip("python-osc niet geïnstalleerd")
    ok, err = eng.send("127.0.0.1", 0, "/x", [])
    assert ok is False
    ok, err = eng.send("127.0.0.1", 99999, "/x", [])
    assert ok is False


# ---- End-to-end via een lokale dispatcher --------------------------------

def _free_udp_port() -> int:
    """Vraag het OS om een vrije UDP-poort. Tussen close en gebruik kan in
    theorie iets anders 'm pakken, maar voor test-doeleinden ruim genoeg."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_engine_sends_to_local_dispatcher(qt_app) -> None:
    """Stuur een OSC-message naar een lokale python-osc dispatcher in
    een aparte thread; verifieer dat address + args correct aankomen."""
    from livefire.engines.osc_out import OscOutputEngine
    try:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import ThreadingOSCUDPServer
    except ImportError:
        pytest.skip("python-osc niet geïnstalleerd")

    port = _free_udp_port()
    received: list = []
    ev = threading.Event()

    def on_msg(addr, *args):
        received.append((addr, list(args)))
        ev.set()

    disp = Dispatcher()
    disp.map("/test/*", on_msg)
    server = ThreadingOSCUDPServer(("127.0.0.1", port), disp)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        eng = OscOutputEngine()
        if not eng.available:
            pytest.skip("python-osc niet geïnstalleerd")
        ok, err = eng.send("127.0.0.1", port, "/test/foo", [42, 0.5, "x"])
        assert ok, err
        assert ev.wait(timeout=1.0), "OSC-message niet ontvangen"
        assert len(received) == 1
        addr, args = received[0]
        assert addr == "/test/foo"
        assert args == [42, 0.5, "x"]
    finally:
        server.shutdown()
        server.server_close()


def test_engine_caches_clients_per_host_port(qt_app) -> None:
    """Tweede send() naar dezelfde host:port hergebruikt de gecachede
    SimpleUDPClient, zodat we niet voor iedere cue een nieuwe socket
    openen."""
    from livefire.engines.osc_out import OscOutputEngine
    eng = OscOutputEngine()
    if not eng.available:
        pytest.skip("python-osc niet geïnstalleerd")

    port = _free_udp_port()
    # Eerste send maakt cache-entry
    eng.send("127.0.0.1", port, "/x", [1])
    assert ("127.0.0.1", port) in eng._clients
    first_client = eng._clients[("127.0.0.1", port)]

    # Tweede send met zelfde key: zelfde client
    eng.send("127.0.0.1", port, "/y", [2])
    assert eng._clients[("127.0.0.1", port)] is first_client

    # Andere port: nieuwe client
    other_port = _free_udp_port()
    eng.send("127.0.0.1", other_port, "/z", [3])
    assert len(eng._clients) == 2

    eng.shutdown()
    assert eng._clients == {}, "shutdown moet cache leegmaken"


def test_engine_evicts_bad_client_on_send_error(qt_app) -> None:
    """Als send_message faalt (bv. door een corrupte client), wordt de
    cache-entry weggegooid zodat een volgende poging schoon herstart."""
    from livefire.engines.osc_out import OscOutputEngine
    eng = OscOutputEngine()
    if not eng.available:
        pytest.skip("python-osc niet geïnstalleerd")

    port = _free_udp_port()
    eng.send("127.0.0.1", port, "/x", [1])
    assert ("127.0.0.1", port) in eng._clients

    # Forceer een fout door de cache-entry te corrumperen
    eng._clients[("127.0.0.1", port)] = "not-a-client"  # type: ignore
    ok, err = eng.send("127.0.0.1", port, "/x", [1])
    assert ok is False
    # De corrupte entry moet zijn opgeruimd
    assert ("127.0.0.1", port) not in eng._clients

    eng.shutdown()


def test_controller_fires_network_cue_end_to_end(qt_app, pro_license) -> None:
    """Volledige flow: PlaybackController.fire_cue() voor een NETWORK-cue
    moet een OSC-message naar de doelhost sturen via de OscOutputEngine."""
    from PyQt6.QtCore import QEventLoop, QTimer
    try:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import ThreadingOSCUDPServer
    except ImportError:
        pytest.skip("python-osc niet geïnstalleerd")
    from livefire.workspace import Workspace
    from livefire.cues import Cue, CueType
    from livefire.playback import PlaybackController

    port = _free_udp_port()
    received: list = []
    ev = threading.Event()

    def on_msg(addr, *args):
        received.append((addr, list(args)))
        ev.set()

    disp = Dispatcher()
    disp.map("/livefire/*", on_msg)
    server = ThreadingOSCUDPServer(("127.0.0.1", port), disp)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        ws = Workspace()
        cue = Cue(
            cue_type=CueType.NETWORK, cue_number="1", name="Trigger Companion",
            network_address="/livefire/show/start",
            network_args="42, 0.5",
            network_host="127.0.0.1",
            network_port=port,
        )
        ws.add_cue(cue)
        ctrl = PlaybackController(ws)
        try:
            ctrl.fire_cue(cue.id)
            # Wacht tot de tick (20ms) de cue door pre_wait → action heeft
            # geduwd én de UDP-roundtrip heeft plaatsgevonden.
            loop = QEventLoop()
            QTimer.singleShot(150, loop.quit)
            loop.exec()
            assert ev.wait(timeout=0.5), "OSC-message niet ontvangen door dispatcher"
            assert received[0] == ("/livefire/show/start", [42, 0.5])
        finally:
            ctrl.shutdown()
    finally:
        server.shutdown()
        server.server_close()

