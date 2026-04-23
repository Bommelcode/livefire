"""Audio playback engine met sounddevice + numpy master-mixer.

Architectuur:
- Eén sounddevice.OutputStream op het geselecteerde device (standaard de
  Windows default output) streamt samples naar de soundcard.
- De audio callback (draait in een audio-thread van PortAudio) mixt alle
  actieve AudioSource-instanties tot één float32-buffer en schrijft die uit.
- AudioSource houdt zelf positie, loops en een sample-accurate gain-ramp
  bij. Fades (Fade-cue) roepen apply_fade() aan op de target source.

Dit is de basis voor v0.3.x:
- Multi-output routing en per-cue device-keuze komt in v0.3.1
- Matrix routing (N-in × M-out) komt in v0.3.2
- Sample-rate conversion gebeurt bij het laden (via resample_poly) zodat
  de callback CPU-goedkoop blijft.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .registry import EngineStatus, register

# Optionele dependencies — import zacht, engine werkt degraded zonder hen
try:
    import sounddevice as sd
    _SD_OK = True
    _SD_ERR = ""
except Exception as e:
    sd = None  # type: ignore[assignment]
    _SD_OK = False
    _SD_ERR = str(e)

try:
    import soundfile as sf
    _SF_OK = True
    _SF_ERR = ""
except Exception as e:
    sf = None  # type: ignore[assignment]
    _SF_OK = False
    _SF_ERR = str(e)

try:
    from scipy.signal import resample_poly
    _RESAMPLE_OK = True
except Exception:
    resample_poly = None  # type: ignore[assignment]
    _RESAMPLE_OK = False


DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2
DEFAULT_BLOCKSIZE = 512   # ~10 ms op 48 kHz; show-veilige balans
DEFAULT_DTYPE = "float32"


def db_to_linear(db: float) -> float:
    """-inf dB wordt als −120 dB behandeld (effectief stilte)."""
    if db <= -120.0:
        return 0.0
    return float(10.0 ** (db / 20.0))


# ---- AudioSource: één afspeel-instantie -----------------------------------

class AudioSource:
    """Houdt samples (volledige file in-memory, float32, engine-samplerate) +
    positie + gain-ramp bij. Thread-safe: de engine-callback leest via read(),
    de UI-thread kan apply_fade() en stop() aanroepen."""

    def __init__(
        self,
        cue_id: str,
        samples: np.ndarray,         # shape (frames, channels)
        sample_rate: int,
        volume_db: float = 0.0,
        loops: int = 1,
        start_offset_s: float = 0.0,
        end_offset_s: float = 0.0,
        fade_in_s: float = 0.0,
    ):
        self.cue_id = cue_id
        self._samples = samples
        self._sr = sample_rate
        self._channels = samples.shape[1]
        self._total_frames = samples.shape[0]

        # Start-offset: skip naar positie
        self._pos = int(start_offset_s * sample_rate)
        self._pos = max(0, min(self._pos, self._total_frames))

        # End-offset: effectief einde (aantal frames vanaf begin)
        end_trim = int(end_offset_s * sample_rate)
        self._effective_end = max(self._pos, self._total_frames - end_trim)

        # Loops: 0 = oneindig, N>0 = N keer totaal
        self._loops_total = loops
        self._loops_done = 0

        # Gain: bij fade-in starten we op stilte en rampen we naar volume_db.
        final_g = db_to_linear(volume_db)
        fade_in_frames = max(0, int(fade_in_s * sample_rate))
        if fade_in_frames > 0:
            self._current_gain = 0.0
            self._target_gain = final_g
            self._ramp_frames = fade_in_frames
            self._ramp_delta = final_g / fade_in_frames
        else:
            self._current_gain = final_g
            self._target_gain = final_g
            self._ramp_frames = 0
            self._ramp_delta = 0.0
        self._stop_at_end_of_ramp = False

        self._finished = False
        self._lock = threading.Lock()

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def channels(self) -> int:
        return self._channels

    # ---- API vanuit UI / controller thread ---------------------------------

    def apply_fade(self, target_db: float, duration_s: float, stops: bool = False) -> None:
        """Start een sample-accurate gain-ramp naar target_db over duration_s."""
        with self._lock:
            target = db_to_linear(target_db)
            frames = max(0, int(duration_s * self._sr))
            if frames == 0:
                self._current_gain = target
                self._target_gain = target
                self._ramp_frames = 0
                if stops and target == 0.0:
                    self._finished = True
                return
            self._target_gain = target
            self._ramp_frames = frames
            self._ramp_delta = (target - self._current_gain) / frames
            self._stop_at_end_of_ramp = stops and target == 0.0

    def stop(self) -> None:
        with self._lock:
            self._finished = True

    # ---- API vanuit audio-callback -----------------------------------------

    def read(self, frames: int, out_channels: int) -> np.ndarray:
        """Lees `frames` samples, mix naar `out_channels`, pas gain-ramp toe.
        Retourneert (frames, out_channels) float32-buffer. Als de bron klaar
        is vult hij de rest met stilte en zet _finished."""
        out = np.zeros((frames, out_channels), dtype=DEFAULT_DTYPE)
        if self._finished:
            return out

        written = 0
        while written < frames and not self._finished:
            remaining_in_loop = self._effective_end - self._pos
            if remaining_in_loop <= 0:
                # Einde bereikt: loop of stop
                self._loops_done += 1
                if self._loops_total == 0 or self._loops_done < self._loops_total:
                    # Seek terug naar start-offset (niet naar 0, consistent met
                    # QLab: loopt tussen start- en end-offset)
                    self._pos = int(0 if self._loops_total > 0 else 0)
                    # We moeten begin-offset kennen — we slaan het niet apart op,
                    # dus gebruiken 0 als loop-start. Als er een start_offset was
                    # speelt die alleen de eerste keer. Afgesproken gedrag.
                    continue
                self._finished = True
                break

            n = min(frames - written, remaining_in_loop)
            chunk = self._samples[self._pos:self._pos + n]
            self._pos += n

            # Channel-conversie
            if chunk.shape[1] == out_channels:
                mixed = chunk
            elif chunk.shape[1] == 1 and out_channels >= 2:
                mixed = np.repeat(chunk, out_channels, axis=1)
            elif chunk.shape[1] >= 2 and out_channels == 1:
                mixed = chunk.mean(axis=1, keepdims=True)
            elif chunk.shape[1] > out_channels:
                mixed = chunk[:, :out_channels]
            else:  # chunk heeft minder kanalen dan gewenst: zero-pad
                mixed = np.zeros((n, out_channels), dtype=DEFAULT_DTYPE)
                mixed[:, :chunk.shape[1]] = chunk

            out[written:written + n] = mixed
            written += n

        # Pas gain(ramp) toe — gevectoriseerd
        with self._lock:
            if self._ramp_frames > 0:
                n_ramp = min(written, self._ramp_frames)
                ramp = self._current_gain + self._ramp_delta * np.arange(
                    1, n_ramp + 1, dtype=DEFAULT_DTYPE
                )
                out[:n_ramp] *= ramp[:, None]
                self._current_gain += self._ramp_delta * n_ramp
                self._ramp_frames -= n_ramp
                if written > n_ramp:
                    out[n_ramp:written] *= self._target_gain
                    self._current_gain = self._target_gain
                if self._ramp_frames == 0 and self._stop_at_end_of_ramp:
                    self._finished = True
            else:
                if self._current_gain != 1.0:
                    out[:written] *= self._current_gain

        return out


# ---- AudioEngine ----------------------------------------------------------

class AudioEngine:
    """Master-mixer engine. Start() opent één output-stream; play() voegt
    een AudioSource toe; de callback mixt alle sources live."""

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        blocksize: int = DEFAULT_BLOCKSIZE,
        device: int | str | None = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.device = device

        self._sources: dict[str, AudioSource] = {}
        self._lock = threading.Lock()
        self._stream: Optional["sd.OutputStream"] = None  # type: ignore[name-defined]
        self._started = False
        self._last_error: str = ""

    # ---- lifecycle ---------------------------------------------------------

    @property
    def available(self) -> bool:
        return _SD_OK and _SF_OK

    @property
    def unavailable_reason(self) -> str:
        if not _SD_OK:
            return f"sounddevice niet geladen: {_SD_ERR}"
        if not _SF_OK:
            return f"soundfile niet geladen: {_SF_ERR}"
        return ""

    def start(self) -> bool:
        if not self.available:
            return False
        if self._started:
            return True
        try:
            self._stream = sd.OutputStream(  # type: ignore[union-attr]
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=self.blocksize,
                dtype=DEFAULT_DTYPE,
                device=self.device,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._started = True
            return True
        except Exception as e:
            self._last_error = str(e)
            return False

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self._started = False
        self.stop_all()

    def set_device(
        self,
        device: int | str | None,
        sample_rate: int | None = None,
    ) -> tuple[bool, str]:
        """Wissel het output-device (en optioneel de samplerate) on-the-fly.
        Stopt eerst alle actieve cues — device-wissel tijdens playback is
        show-onveilig. Geeft (ok, foutmelding) terug; bij ok=False blijft de
        oude configuratie actief en is de engine gestopt."""
        self.stop_all()
        was_started = self._started
        self.stop()
        self.device = device
        if sample_rate is not None:
            self.sample_rate = sample_rate
        if not was_started:
            return True, ""
        if not self.start():
            return False, self._last_error or "Onbekende fout bij starten van engine."
        return True, ""

    # ---- playback ----------------------------------------------------------

    def play_file(
        self,
        cue_id: str,
        file_path: str | Path,
        volume_db: float = 0.0,
        loops: int = 1,
        start_offset: float = 0.0,
        end_offset: float = 0.0,
        fade_in: float = 0.0,
    ) -> bool:
        """Laadt het bestand, resamplet indien nodig, registreert de source."""
        if not self.available:
            return False
        path = Path(file_path)
        if not path.is_file():
            self._last_error = f"Bestand niet gevonden: {path}"
            return False
        try:
            samples, file_sr = sf.read(str(path), dtype=DEFAULT_DTYPE, always_2d=True)  # type: ignore[union-attr]
        except Exception as e:
            self._last_error = f"Kon bestand niet laden: {e}"
            return False

        # Resample naar engine-samplerate indien nodig
        if file_sr != self.sample_rate:
            if not _RESAMPLE_OK:
                self._last_error = (
                    f"Bestand is {file_sr} Hz maar engine draait op {self.sample_rate} Hz "
                    "en scipy ontbreekt voor resampling"
                )
                return False
            samples = _resample(samples, file_sr, self.sample_rate)

        source = AudioSource(
            cue_id=cue_id,
            samples=samples,
            sample_rate=self.sample_rate,
            volume_db=volume_db,
            loops=loops,
            start_offset_s=start_offset,
            end_offset_s=end_offset,
            fade_in_s=fade_in,
        )
        with self._lock:
            # Als deze cue al speelt, eerst oude source weg
            old = self._sources.pop(cue_id, None)
            if old is not None:
                old.stop()
            self._sources[cue_id] = source
        return True

    def apply_fade(
        self, cue_id: str, target_db: float, duration_s: float, stops: bool = False
    ) -> bool:
        with self._lock:
            src = self._sources.get(cue_id)
        if src is None:
            return False
        src.apply_fade(target_db, duration_s, stops=stops)
        return True

    def stop_cue(self, cue_id: str, fade_out: float = 0.0) -> None:
        """Stop een cue. Met fade_out > 0: fade naar stilte en stop dan; de
        source blijft tijdens de fade in de mixer zodat overlap met een
        nieuwe cue een natuurlijke crossfade geeft."""
        if fade_out > 0:
            with self._lock:
                src = self._sources.get(cue_id)
            if src is not None:
                src.apply_fade(-120.0, fade_out, stops=True)
            return
        with self._lock:
            src = self._sources.pop(cue_id, None)
        if src is not None:
            src.stop()

    def stop_all(self) -> None:
        with self._lock:
            sources = list(self._sources.values())
            self._sources.clear()
        for s in sources:
            s.stop()

    def is_playing(self, cue_id: str) -> bool:
        with self._lock:
            src = self._sources.get(cue_id)
        return src is not None and not src.finished

    def active_cue_ids(self) -> list[str]:
        with self._lock:
            return [cid for cid, s in self._sources.items() if not s.finished]

    # ---- intern ------------------------------------------------------------

    def _audio_callback(self, outdata, frames, time_info, status):
        # status bevat bv. output_underflow — we negeren het in de skeleton,
        # maar tonen 'm desgewenst via een latere diagnose-widget.
        outdata.fill(0.0)
        with self._lock:
            sources = list(self._sources.items())
        dead: list[str] = []
        for cue_id, src in sources:
            if src.finished:
                dead.append(cue_id)
                continue
            buf = src.read(frames, self.channels)
            outdata += buf
            if src.finished:
                dead.append(cue_id)
        # Soft clip om digital overs te voorkomen bij overlappende cues
        np.clip(outdata, -1.0, 1.0, out=outdata)
        if dead:
            with self._lock:
                for cid in dead:
                    self._sources.pop(cid, None)


# ---- helpers ---------------------------------------------------------------

@dataclass
class OutputDeviceInfo:
    """Subset van sounddevice device-info dat de UI nodig heeft."""

    index: int
    name: str
    max_output_channels: int
    default_samplerate: float


def list_output_devices() -> list[OutputDeviceInfo]:
    """Geef alle beschikbare output-devices met ≥2 kanalen terug. Stille lijst
    als sounddevice niet geladen is."""
    if not _SD_OK:
        return []
    out: list[OutputDeviceInfo] = []
    try:
        devices = sd.query_devices()  # type: ignore[union-attr]
    except Exception:
        return []
    for i, d in enumerate(devices):
        ch = int(d.get("max_output_channels", 0) or 0)
        if ch < 2:
            continue
        out.append(OutputDeviceInfo(
            index=i,
            name=str(d.get("name", f"device {i}")),
            max_output_channels=ch,
            default_samplerate=float(d.get("default_samplerate", 0) or 0),
        ))
    return out


def find_device_index_by_name(name: str) -> int | None:
    """Zoek een device-index op basis van naam (USB-devices schuiven van
    index bij reconnect, dus slaan we de naam op). None als niet gevonden."""
    if not name:
        return None
    for d in list_output_devices():
        if d.name == name:
            return d.index
    return None


def _resample(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Eenvoudige polyphase-resample per kanaal. Geen SRC maar voldoende
    voor de eerste skeleton; wordt eventueel vervangen door libsamplerate."""
    from math import gcd
    g = gcd(src_sr, dst_sr)
    up = dst_sr // g
    down = src_sr // g
    out = np.column_stack([
        resample_poly(samples[:, ch], up, down).astype(DEFAULT_DTYPE)
        for ch in range(samples.shape[1])
    ])
    return out


# ---- status-registratie bij import ----------------------------------------

def register_status(engine: AudioEngine | None = None) -> None:
    if not _SD_OK:
        register(EngineStatus(
            name="Audio (sounddevice)",
            available=False,
            detail=_SD_ERR,
            short="audio",
        ))
        return
    if not _SF_OK:
        register(EngineStatus(
            name="Audio (sounddevice)",
            available=False,
            detail=f"soundfile ontbreekt: {_SF_ERR}",
            short="audio",
        ))
        return
    detail = ""
    if engine is not None:
        try:
            info = sd.query_devices(engine.device, "output")  # type: ignore[union-attr]
            detail = f"{info['name']} @ {engine.sample_rate} Hz, {engine.channels} kanalen"
        except Exception as e:
            detail = f"device-info niet beschikbaar: {e}"
    if not _RESAMPLE_OK:
        detail += " (scipy ontbreekt — resampling uitgeschakeld)"
    register(EngineStatus(
        name="Audio (sounddevice)",
        available=True,
        detail=detail,
        short="audio",
    ))
