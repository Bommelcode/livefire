"""Tests voor preload-cache + immediate-fire bij pre_wait=0.

Beide optimalisaties zijn gedaan om de OSC-trigger latency naar onder
de tick-tijd te krijgen zodat Stream Deck → Companion → liveFire snel
voelt."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest


def _write_wav(path: Path, duration_s: float = 1.0, sr: int = 48000) -> None:
    """Schrijf een korte zwijgende stereo WAV — genoeg om soundfile
    'm te kunnen lezen, klein genoeg om snel te zijn."""
    try:
        import soundfile as sf
    except ImportError:
        pytest.skip("soundfile niet geïnstalleerd")
    n = int(duration_s * sr)
    samples = np.zeros((n, 2), dtype=np.float32)
    sf.write(str(path), samples, sr)


def test_preload_caches_samples(tmp_path) -> None:
    """preload() leest 'n bestand in en de cache-key matcht (mtime+size)."""
    from livefire.engines.audio import AudioEngine
    wav = tmp_path / "a.wav"
    _write_wav(wav)
    eng = AudioEngine()
    if not eng.available:
        pytest.skip("audio engine niet beschikbaar")
    assert eng.preload(wav)
    key = str(wav.resolve())
    assert key in eng._preload


def test_preload_skips_redundant_read(tmp_path) -> None:
    """Tweede preload() voor hetzelfde ongewijzigde bestand mag de
    cache niet opnieuw vullen — controleert dat er geen onnodige IO is."""
    from livefire.engines.audio import AudioEngine
    wav = tmp_path / "a.wav"
    _write_wav(wav)
    eng = AudioEngine()
    if not eng.available:
        pytest.skip("audio engine niet beschikbaar")
    assert eng.preload(wav)
    cached_first = eng._preload[str(wav.resolve())][0]
    assert eng.preload(wav)
    cached_second = eng._preload[str(wav.resolve())][0]
    # Identiteits-check: de array-objecten zijn dezelfde (geen re-read)
    assert cached_first is cached_second


def test_preload_invalidates_on_mtime_change(tmp_path) -> None:
    """Een bestand dat na preload wijzigt, wordt opnieuw gelezen."""
    from livefire.engines.audio import AudioEngine
    wav = tmp_path / "a.wav"
    _write_wav(wav, duration_s=0.5)
    eng = AudioEngine()
    if not eng.available:
        pytest.skip("audio engine niet beschikbaar")
    assert eng.preload(wav)
    cached_first = eng._preload[str(wav.resolve())][0]

    # Schrijf opnieuw, andere lengte → andere size + mtime
    time.sleep(0.05)  # zorg dat mtime verschilt op grove filesystems
    _write_wav(wav, duration_s=1.0)
    assert eng.preload(wav)
    cached_second = eng._preload[str(wav.resolve())][0]
    assert cached_first is not cached_second
    assert cached_second.shape[0] > cached_first.shape[0]


def test_play_file_uses_cache_when_available(tmp_path) -> None:
    """Na preload moet play_file zonder disk-IO terugkomen."""
    from livefire.engines.audio import AudioEngine
    wav = tmp_path / "a.wav"
    _write_wav(wav)
    eng = AudioEngine()
    if not eng.available:
        pytest.skip("audio engine niet beschikbaar")
    assert eng.preload(wav)

    # Mock _read_and_resample zodat een onverwachte read meteen opvalt
    eng._read_and_resample = lambda *a, **kw: pytest.fail(  # type: ignore[assignment]
        "play_file mag geen disk-read doen na preload"
    )
    ok = eng.play_file("c1", wav)
    assert ok


def test_play_file_falls_back_when_not_preloaded(tmp_path) -> None:
    """Zonder preload werkt play_file gewoon synchroon (backwards compat)."""
    from livefire.engines.audio import AudioEngine
    wav = tmp_path / "a.wav"
    _write_wav(wav)
    eng = AudioEngine()
    if not eng.available:
        pytest.skip("audio engine niet beschikbaar")
    ok = eng.play_file("c1", wav)
    assert ok
    # Na de play-call zit het bestand alsnog in de cache zodat de tweede
    # GO instant is.
    assert str(wav.resolve()) in eng._preload


def test_evict_preload_removes_entry(tmp_path) -> None:
    from livefire.engines.audio import AudioEngine
    wav = tmp_path / "a.wav"
    _write_wav(wav)
    eng = AudioEngine()
    if not eng.available:
        pytest.skip("audio engine niet beschikbaar")
    eng.preload(wav)
    assert str(wav.resolve()) in eng._preload
    eng.evict_preload(wav)
    assert str(wav.resolve()) not in eng._preload


def test_controller_immediate_fire_at_pre_wait_zero(qt_app, tmp_path) -> None:
    """Bij pre_wait=0 moet ``_begin_action`` synchroon vanuit
    ``_start_cue`` worden aangeroepen zodat de OSC-trigger latency niet
    één tick (20ms) extra kost. Een Memo-cue is licht genoeg om te
    meten zonder engine-side-effecten."""
    from livefire.workspace import Workspace
    from livefire.cues import Cue, CueType
    from livefire.playback import PlaybackController

    ws = Workspace()
    cue = Cue(cue_type=CueType.MEMO, cue_number="1", name="memo", pre_wait=0.0)
    ws.add_cue(cue)
    ctrl = PlaybackController(ws)
    try:
        ctrl.fire_cue(cue.id)
        # Direct (geen processEvents, geen tick) — de running entry moet
        # nu al in 'action'-fase zitten.
        running = ctrl._running.get(cue.id)
        assert running is not None
        assert running.phase == "action", \
            f"verwacht 'action', kreeg '{running.phase}' (1-tick latency niet weg)"
    finally:
        ctrl.shutdown()


def test_controller_pre_wait_nonzero_still_starts_in_pre_wait_phase(qt_app) -> None:
    """Cues met expliciete pre_wait > 0 moeten alsnog netjes door de
    pre_wait-fase gaan; we mogen die optimalisatie niet scheef trekken."""
    from livefire.workspace import Workspace
    from livefire.cues import Cue, CueType
    from livefire.playback import PlaybackController

    ws = Workspace()
    cue = Cue(cue_type=CueType.MEMO, cue_number="1", name="delayed", pre_wait=0.5)
    ws.add_cue(cue)
    ctrl = PlaybackController(ws)
    try:
        ctrl.fire_cue(cue.id)
        running = ctrl._running.get(cue.id)
        assert running is not None
        assert running.phase == "pre_wait"
    finally:
        ctrl.shutdown()


# ---- WASAPI exclusive mode ------------------------------------------------

def test_audio_engine_default_shared_mode() -> None:
    """Default: exclusive_mode is uit zodat liveFire braaf naast andere
    apps kan draaien."""
    from livefire.engines.audio import AudioEngine
    e = AudioEngine()
    assert e.exclusive_mode is False


def test_audio_engine_accepts_exclusive_mode_flag() -> None:
    from livefire.engines.audio import AudioEngine
    e = AudioEngine(exclusive_mode=True)
    assert e.exclusive_mode is True


def test_set_device_can_toggle_exclusive_mode() -> None:
    """set_device(... exclusive_mode=True) moet het attribuut bijwerken
    ook als de engine nog niet gestart is."""
    from livefire.engines.audio import AudioEngine
    e = AudioEngine()
    ok, _err = e.set_device(None, exclusive_mode=True)
    # set_device met was_started=False geeft ok=True zonder start()
    assert ok
    assert e.exclusive_mode is True
    ok, _err = e.set_device(None, exclusive_mode=False)
    assert ok
    assert e.exclusive_mode is False


def test_find_wasapi_device_returns_none_on_non_windows() -> None:
    """Op niet-Windows is er geen WASAPI host API — helper moet None
    geven zodat de engine schoon terugvalt op shared mode."""
    from livefire.engines.audio import AudioEngine
    # Linux/macOS test environments — geen WASAPI
    assert AudioEngine._find_wasapi_device(None) is None
    assert AudioEngine._find_wasapi_device(0) is None
    assert AudioEngine._find_wasapi_device("Speakers") is None
