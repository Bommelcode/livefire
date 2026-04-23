"""Cue dataclasses. Elke cue heeft een type-discriminator zodat we ze via
dictionary-lookup serialiseren/deserialiseren zonder isinstance-ketens."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


class CueType:
    """String constants voor cue-types. Bewust een plain class en geen Enum
    omdat we ze direct in JSON opslaan."""

    AUDIO = "Audio"
    GROUP = "Group"
    WAIT = "Wait"
    STOP = "Stop"
    FADE = "Fade"
    MEMO = "Memo"
    START = "Start"

    # Toekomstige types (nog niet geïmplementeerd in v0.3.0):
    # VIDEO = "Video"   -> v0.6.0
    # MIDI  = "MIDI"    -> v0.4.0
    # OSC   = "OSC"     -> v0.4.0
    # DMX   = "DMX"     -> v0.5.0

    ALL = [AUDIO, GROUP, WAIT, STOP, FADE, START, MEMO]


class ContinueMode:
    """Hoe de playback verder gaat na deze cue."""

    DO_NOT_CONTINUE = 0
    AUTO_CONTINUE = 1   # volgende cue start zodra déze cue zijn actie start
    AUTO_FOLLOW = 2     # volgende cue start wanneer déze cue klaar is

    LABELS = {
        DO_NOT_CONTINUE: "Do Not Continue",
        AUTO_CONTINUE: "Auto-Continue",
        AUTO_FOLLOW: "Auto-Follow",
    }


@dataclass
class Cue:
    """Platte cue-dataclass. Alle type-specifieke velden staan hier zodat
    de serialisatie eenvoudig blijft; de UI verbergt irrelevante velden."""

    # Identiteit & algemeen
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cue_number: str = ""
    cue_type: str = CueType.AUDIO
    name: str = ""
    notes: str = ""
    color: str = ""  # hex, leeg = default

    # Timing
    pre_wait: float = 0.0
    duration: float = 0.0      # 0 = auto (bestandslengte voor audio)
    post_wait: float = 0.0
    continue_mode: int = ContinueMode.DO_NOT_CONTINUE

    # Audio / Fade
    file_path: str = ""
    volume_db: float = 0.0
    loops: int = 1             # 1 = 1x, 0 = oneindig, N = N keer
    audio_start_offset: float = 0.0
    audio_end_offset: float = 0.0
    audio_fade_in: float = 0.0   # s, 0 = hard in
    audio_fade_out: float = 0.0  # s, 0 = hard out

    # Fade-target
    target_cue_id: str = ""    # voor Stop, Fade, Start
    fade_target_db: float = 0.0  # Fade: doelvolume
    fade_stops_target: bool = False  # na fade-out: target stoppen?

    # Wait
    wait_duration: float = 1.0

    # Groepsgedrag
    group_mode: str = "list"   # "list" | "first-then-list"

    # Runtime-only (niet geserialiseerd)
    state: str = field(default="idle", compare=False)  # idle|running|finished

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("state", None)  # runtime-only
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Cue":
        # Filter onbekende sleutels zodat oudere/andere versies niet crashen
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        clean = {k: v for k, v in d.items() if k in known}
        return cls(**clean)
