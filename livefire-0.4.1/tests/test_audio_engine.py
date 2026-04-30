"""Tests voor de audio-engine configuratie-API (device-lijst, naam-resolutie,
set_device lifecycle zonder echte playback). Vereist geen echte audio-hardware."""

from __future__ import annotations

import pytest

from livefire.engines.audio import (
    AudioEngine, OutputDeviceInfo, list_output_devices,
    find_device_index_by_name,
)


def test_list_output_devices_returns_list():
    """Moet altijd een lijst teruggeven; leeg is geldig (bv. op CI zonder audio)."""
    devices = list_output_devices()
    assert isinstance(devices, list)
    for d in devices:
        assert isinstance(d, OutputDeviceInfo)
        assert d.max_output_channels >= 2   # filter: alleen stereo+


def test_find_device_index_by_name_unknown_returns_none():
    assert find_device_index_by_name("zzz-bestaat-niet-zzz") is None


def test_find_device_index_by_name_empty_returns_none():
    assert find_device_index_by_name("") is None


def test_find_device_index_roundtrip():
    """Elke device-naam moet vindbaar zijn. Op Windows exposeert sounddevice
    dezelfde hardware via meerdere host-API's (MME/DirectSound/WASAPI/WDM-KS)
    met dezelfde naam; we vereisen dan ook alleen dat de gevonden index één
    van de matches is, niet per se precies deze."""
    devices = list_output_devices()
    if not devices:
        pytest.skip("geen output-devices op deze host")
    by_name: dict[str, set[int]] = {}
    for d in devices:
        by_name.setdefault(d.name, set()).add(d.index)
    for name, indices in by_name.items():
        found = find_device_index_by_name(name)
        assert found in indices, f"{name}: {found} niet in {indices}"


def test_set_device_on_stopped_engine_updates_config():
    """set_device() op een nog niet gestarte engine past alleen config aan
    en probeert niet te starten."""
    eng = AudioEngine(sample_rate=48000, device=None)
    ok, err = eng.set_device(None, sample_rate=44100)
    assert ok, err
    assert eng.sample_rate == 44100
    assert eng.device is None


def test_audio_source_fade_in_ramps_from_silence():
    """Een AudioSource met fade_in_s > 0 start bij 0.0 en ramped naar het
    volume-doel — zodat overlappende cues een natuurlijke crossfade geven."""
    import numpy as np
    from livefire.engines.audio import AudioSource

    sr = 48000
    frames = sr  # 1 s mono->stereo signaal op volle sterkte
    samples = np.ones((frames, 2), dtype=np.float32)

    src = AudioSource(
        cue_id="x", samples=samples, sample_rate=sr,
        volume_db=0.0, loops=1, fade_in_s=0.5,
    )
    # Eerste sample vlak na start: gain ≈ 0 → output ≈ 0
    out = src.read(1, 2)
    assert abs(out[0, 0]) < 0.01, f"start van fade-in niet stil: {out[0, 0]}"

    # Na de volledige fade-in-duur: gain op target (1.0) → output ≈ 1.0
    src2 = AudioSource(
        cue_id="y", samples=samples, sample_rate=sr,
        volume_db=0.0, loops=1, fade_in_s=0.5,
    )
    _ = src2.read(int(0.5 * sr), 2)   # eet de fade-in op
    tail = src2.read(100, 2)
    assert tail[0, 0] > 0.95, f"eind van fade-in niet op target: {tail[0, 0]}"


def test_audio_source_no_fade_in_plays_at_volume_immediately():
    import numpy as np
    from livefire.engines.audio import AudioSource

    sr = 48000
    samples = np.ones((sr, 2), dtype=np.float32)
    src = AudioSource(cue_id="z", samples=samples, sample_rate=sr,
                      volume_db=0.0, loops=1, fade_in_s=0.0)
    out = src.read(10, 2)
    assert out[0, 0] > 0.99, f"zonder fade-in niet direct op volume: {out[0, 0]}"
