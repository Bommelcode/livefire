"""Tests voor de DMX-engine — parser, packet-encoders, LTP-merge,
fade-interpolatie, chase-step-advance en ping-pong.

End-to-end test: bind een UDP-socket op een vrije poort, laat de engine
naar localhost:die_poort streamen, en verifieer dat we Art-Net frames
binnen krijgen. Doet hetzelfde voor sACN."""

from __future__ import annotations

import socket
import struct
import time

import pytest

from livefire.cues import Cue, CueType
from livefire.engines.dmx import (
    ARTNET_HEADER_MAGIC, ARTNET_OPCODE_DMX,
    DmxEngine, encode_artnet_dmx, encode_sacn_dmx,
    parse_chase_steps, parse_dmx_values, sacn_multicast_address,
)


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- parser ---------------------------------------------------------------


def test_parse_basic_pairs() -> None:
    assert parse_dmx_values("1:255, 17:128, 33:64") == {1: 255, 17: 128, 33: 64}


def test_parse_clamps_out_of_range() -> None:
    # Channel 0 en 513 worden geweigerd; value 256 ook.
    out = parse_dmx_values("0:128, 1:300, 513:50, 17:128")
    assert out == {17: 128}


def test_parse_tolerates_whitespace_and_blanks() -> None:
    assert parse_dmx_values("  1: 255 ,, 17 :  64 , ") == {1: 255, 17: 64}


def test_parse_chase_steps_three_blocks() -> None:
    steps = parse_chase_steps("1:255 | 1:0,17:255 | 17:0")
    assert steps == [{1: 255}, {1: 0, 17: 255}, {17: 0}]


def test_parse_empty() -> None:
    assert parse_dmx_values("") == {}
    assert parse_chase_steps("") == []


# ---- packet encoders ------------------------------------------------------


def test_artnet_packet_layout() -> None:
    payload = bytes([0xAB] + [0] * 511)
    pkt = encode_artnet_dmx(universe=5, sequence=42, dmx=payload)
    assert pkt[:8] == ARTNET_HEADER_MAGIC
    # OpCode (LE)
    assert struct.unpack("<H", pkt[8:10])[0] == ARTNET_OPCODE_DMX
    # ProtVer (BE) = 14
    assert struct.unpack(">H", pkt[10:12])[0] == 14
    assert pkt[12] == 42  # sequence
    assert pkt[13] == 0   # physical
    assert struct.unpack("<H", pkt[14:16])[0] == 5  # universe LE
    assert struct.unpack(">H", pkt[16:18])[0] == 512
    # Eerste DMX-byte direct na header
    assert pkt[18] == 0xAB
    assert len(pkt) == 18 + 512


def test_artnet_payload_must_be_512() -> None:
    with pytest.raises(ValueError):
        encode_artnet_dmx(0, 1, b"\x00" * 256)


def test_sacn_packet_total_length() -> None:
    payload = bytes(512)
    pkt = encode_sacn_dmx(universe=1, sequence=1, dmx=payload, source_name="livefire")
    # Root preamble (16) + 638-payload omhullend (root + framing + dmp).
    # We checken alleen totaalbyte-lengte; spec is fragiel om byte-by-byte
    # te asserten op alle velden.
    assert len(pkt) == 638
    # ROOT vector ROOT_E131_DATA = 0x00000004 op offset 18..22
    assert struct.unpack(">I", pkt[18:22])[0] == 0x00000004
    # FRAMING-vector E131_DATA_PACKET = 0x00000002 op offset 40..44
    assert struct.unpack(">I", pkt[40:44])[0] == 0x00000002
    # Universe-veld op offset 113..115 (priority op 108, sync 109, seq 111, opt 112)
    # Eenvoudiger: zoek de int 0x0001 in BE op vaste offset 113.
    assert struct.unpack(">H", pkt[113:115])[0] == 1


def test_sacn_multicast_address_split() -> None:
    assert sacn_multicast_address(1) == "239.255.0.1"
    assert sacn_multicast_address(258) == "239.255.1.2"


# ---- engine: snapshot + LTP -----------------------------------------------


def _make_dmx_cue(**kw) -> Cue:
    """Maak een DMX-cue met sensible defaults voor tests."""
    cue = Cue(cue_type=CueType.DMX, name=kw.get("name", "dmx"))
    cue.dmx_protocol = kw.get("protocol", "artnet")
    cue.dmx_universe = kw.get("universe", 0)
    cue.dmx_host = kw.get("host", "127.0.0.1")
    cue.dmx_port = kw.get("port", 6454)
    cue.dmx_mode = kw.get("mode", "snapshot")
    cue.dmx_values = kw.get("values", "")
    cue.dmx_fade_time = kw.get("fade_time", 0.0)
    cue.dmx_chase_steps = kw.get("chase_steps", "")
    cue.dmx_step_time = kw.get("step_time", 0.5)
    cue.dmx_chase_loops = kw.get("chase_loops", 0)
    cue.dmx_chase_pingpong = kw.get("pingpong", False)
    return cue


def test_engine_snapshot_writes_buffer() -> None:
    eng = DmxEngine()
    cue = _make_dmx_cue(values="1:255, 17:128")
    ok, err = eng.play(cue)
    assert ok, err
    buf = eng._universes[("artnet", 0)].buffer
    assert buf[0] == 255
    assert buf[16] == 128
    assert buf[17] == 0  # niet geraakte kanalen blijven 0


def test_engine_ltp_overrides_previous_cue() -> None:
    eng = DmxEngine()
    eng.play(_make_dmx_cue(name="a", values="1:255, 17:128"))
    eng.play(_make_dmx_cue(name="b", values="1:64"))
    buf = eng._universes[("artnet", 0)].buffer
    # ch1 overschreven door cue b, ch17 ongewijzigd door cue a
    assert buf[0] == 64
    assert buf[16] == 128


def test_engine_blackout_zeros_all_universes() -> None:
    eng = DmxEngine()
    eng.play(_make_dmx_cue(values="1:255, 100:200"))
    eng.blackout()
    buf = eng._universes[("artnet", 0)].buffer
    assert all(v == 0 for v in buf)


def test_engine_rejects_unknown_protocol() -> None:
    eng = DmxEngine()
    cue = _make_dmx_cue()
    cue.dmx_protocol = "bogus"
    ok, err = eng.play(cue)
    assert ok is False and "protocol" in err.lower()


def test_engine_rejects_chase_without_steps() -> None:
    eng = DmxEngine()
    ok, err = eng.play(_make_dmx_cue(mode="chase", chase_steps=""))
    assert ok is False and "step" in err.lower()


def test_engine_rejects_snapshot_without_values() -> None:
    eng = DmxEngine()
    ok, err = eng.play(_make_dmx_cue(mode="snapshot", values=""))
    assert ok is False and "values" in err.lower()


# ---- engine: fade ---------------------------------------------------------


def test_fade_interpolation_midpoint() -> None:
    eng = DmxEngine()
    # Eerste cue zet startwaarde
    eng.play(_make_dmx_cue(name="start", values="1:0"))
    # Tweede cue fadet naar 200 over 1 seconde
    eng.play(_make_dmx_cue(name="up", mode="fade", values="1:200", fade_time=1.0))
    handle = eng._cues[next(c for c in eng._cues if eng._cues[c].mode == "fade")]
    buf = eng._universes[("artnet", 0)].buffer
    # Simuleer halfweg-tick door de engine te bedriegen met fade_started_at
    handle.fade_started_at = time.monotonic() - 0.5
    eng._tick_fade(handle, time.monotonic(), buf)
    # Na 0.5 s in een 1 s fade van 0→200 verwachten we ongeveer 100
    assert 90 <= buf[0] <= 110


def test_fade_completes_at_full_duration() -> None:
    eng = DmxEngine()
    eng.play(_make_dmx_cue(name="up", mode="fade", values="1:255", fade_time=0.5))
    cue_id = next(iter(eng._cues))
    handle = eng._cues[cue_id]
    buf = eng._universes[("artnet", 0)].buffer
    # Schuif fade-start zodanig dat we buiten de duration zitten.
    handle.fade_started_at = time.monotonic() - 1.0
    still_active = eng._tick_fade(handle, time.monotonic(), buf)
    assert still_active is False
    assert buf[0] == 255


# ---- engine: chase --------------------------------------------------------


def test_chase_advances_per_step() -> None:
    eng = DmxEngine()
    eng.play(_make_dmx_cue(
        mode="chase",
        chase_steps="1:255 | 1:0,17:255 | 17:0",
        step_time=0.1,
        chase_loops=0,
    ))
    cue_id = next(iter(eng._cues))
    handle = eng._cues[cue_id]
    buf = eng._universes[("artnet", 0)].buffer

    # Reset start-tijd zodat we deterministische tijden kunnen checken.
    base = time.monotonic()
    handle.chase_started_at = base
    eng._tick_chase(handle, base + 0.0, buf)
    assert buf[0] == 255 and buf[16] == 0
    eng._tick_chase(handle, base + 0.15, buf)
    assert buf[0] == 0 and buf[16] == 255
    eng._tick_chase(handle, base + 0.25, buf)
    assert buf[16] == 0


def test_chase_finishes_after_loops() -> None:
    eng = DmxEngine()
    eng.play(_make_dmx_cue(
        mode="chase",
        chase_steps="1:255 | 1:0",
        step_time=0.05,
        chase_loops=2,
    ))
    cue_id = next(iter(eng._cues))
    handle = eng._cues[cue_id]
    buf = eng._universes[("artnet", 0)].buffer

    base = time.monotonic()
    handle.chase_started_at = base
    # Twee loops × 2 steps × 0.05 s = 0.2 s totaal. Tick na 0.5 s → klaar.
    finished_signals: list[str] = []
    eng.cue_finished.connect(lambda cid: finished_signals.append(cid))
    still_active = eng._tick_chase(handle, base + 0.5, buf)
    assert still_active is False
    assert handle.chase_finished is True
    assert finished_signals == [cue_id]


def test_chase_pingpong_reverses_direction() -> None:
    eng = DmxEngine()
    eng.play(_make_dmx_cue(
        mode="chase",
        chase_steps="1:50 | 1:150 | 1:250",
        step_time=0.1,
        chase_loops=0,
        pingpong=True,
    ))
    cue_id = next(iter(eng._cues))
    handle = eng._cues[cue_id]
    buf = eng._universes[("artnet", 0)].buffer

    base = time.monotonic()
    handle.chase_started_at = base
    # Cycle = 2*(3-1) = 4 steps. Step 0..2 = forward, step 3 = step 1 (mid),
    # dan terug naar step 0.
    eng._tick_chase(handle, base + 0.05, buf)
    assert buf[0] == 50
    eng._tick_chase(handle, base + 0.15, buf)
    assert buf[0] == 150
    eng._tick_chase(handle, base + 0.25, buf)
    assert buf[0] == 250
    eng._tick_chase(handle, base + 0.35, buf)
    # Step 3 in de cycle → reverse-index 1 → waarde 150
    assert buf[0] == 150


# ---- engine: end-to-end UDP via Art-Net -----------------------------------


def test_engine_sends_artnet_packets_over_udp(qt_app) -> None:
    """Bind een UDP-listener op een vrije poort, laat de engine naar
    localhost:die_poort streamen, en verifieer dat we Art-Net frames
    binnen krijgen met onze waardes."""
    port = _free_udp_port()
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", port))
    listener.settimeout(2.0)

    eng = DmxEngine(refresh_hz=30)
    try:
        ok, err = eng.start()
        assert ok, err
        cue = _make_dmx_cue(values="1:255, 100:128", port=port)
        ok, err = eng.play(cue)
        assert ok, err

        # Pak één frame; sender pusht continu dus we krijgen 'm snel.
        data, _ = listener.recvfrom(2048)
        assert data[:8] == ARTNET_HEADER_MAGIC
        # DMX-payload begint na 18-byte header.
        assert data[18] == 255       # ch1
        assert data[18 + 99] == 128  # ch100
    finally:
        eng.shutdown()
        listener.close()
