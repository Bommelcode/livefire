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
    VIDEO = "Video"
    IMAGE = "Image"
    PRESENTATION = "Presentation"
    NETWORK = "Network"
    GROUP = "Group"
    WAIT = "Wait"
    STOP = "Stop"
    FADE = "Fade"
    MEMO = "Memo"
    START = "Start"

    # Toekomstige types (nog niet geïmplementeerd):
    # MIDI  = "MIDI"    -> v0.4.x
    # DMX   = "DMX"     -> v0.5.0

    ALL = [AUDIO, VIDEO, IMAGE, PRESENTATION, NETWORK, GROUP, WAIT, STOP, FADE, START, MEMO]


class PresentationAction:
    """Sub-actie van een Presentation-cue."""

    OPEN = "open"
    NEXT = "next"
    PREVIOUS = "previous"
    GOTO = "goto"
    CLOSE = "close"

    LABELS = {
        OPEN: "Open presentatie",
        NEXT: "Volgende slide",
        PREVIOUS: "Vorige slide",
        GOTO: "Ga naar slide",
        CLOSE: "Sluit presentatie",
    }
    ALL = [OPEN, NEXT, PREVIOUS, GOTO, CLOSE]


class ContinueMode:
    """Hoe de playback verder gaat na deze cue."""

    DO_NOT_CONTINUE = 0
    AUTO_CONTINUE = 1   # volgende cue start zodra déze cue zijn actie start
    AUTO_FOLLOW = 2     # volgende cue start wanneer déze cue klaar is

    # i18n-keys; de display-labels worden via livefire.i18n.t() opgehaald
    # zodat een taalwijziging in de UI doorkomt zonder workspace-migratie.
    KEYS = {
        DO_NOT_CONTINUE: "continue.do_not",
        AUTO_CONTINUE:   "continue.auto_continue",
        AUTO_FOLLOW:     "continue.auto_follow",
    }

    @staticmethod
    def label(mode: int) -> str:
        from ..i18n import t
        return t(ContinueMode.KEYS.get(mode, "continue.do_not"))


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

    # Video (v0.6.0 MVP)
    video_output_screen: int = 0     # index in QGuiApplication.screens()
    video_fade_in: float = 0.0       # s, 0 = hard in
    video_fade_out: float = 0.0      # s, 0 = fade-to-black uit
    video_start_offset: float = 0.0  # in-punt in seconden (0 = vanaf begin)
    video_end_offset: float = 0.0    # uit-punt in seconden (0 = tot einde)
    video_file_duration: float = 0.0 # cache van file-duur; auto-gevuld door preview
    video_last_frame_store: bool = False  # True = behoud laatste frame na einde, False = zwart

    # Image (v0.4.1 — voor ingebedde slides en losse afbeeldingen)
    image_output_screen: int = 0     # zelfde indexering als video
    image_fade_in: float = 0.0       # s, 0 = hard in
    image_fade_out: float = 0.0      # s, 0 = hard uit

    # PowerPoint-presentatie
    presentation_action: str = PresentationAction.OPEN
    presentation_slide: int = 1     # alleen voor GOTO

    # Network (OSC-out, v0.4.1)
    # Adres: bv. "/companion/page/1/button/1" of "/livefire/show/start"
    # Args: vrije tekst, comma-separated. Token-parsing: int → float → string,
    # met "..."-quoting voor strings met spaties of komma's.
    # Host: hostname of IP, default 127.0.0.1.
    # Port: UDP-poort van de ontvanger (Companion default = 12321, QLab = 53000).
    network_address: str = ""
    network_args: str = ""
    network_host: str = "127.0.0.1"
    network_port: int = 53000

    # Fade-target
    target_cue_id: str = ""    # voor Stop, Fade, Start
    fade_target_db: float = 0.0  # Fade: doelvolume
    fade_stops_target: bool = False  # na fade-out: target stoppen?

    # Wait
    wait_duration: float = 1.0

    # Groepsgedrag
    group_mode: str = "list"   # "list" | "first-then-list"

    # Triggers (v0.4.0)
    trigger_osc: str = ""      # OSC-address dat deze cue afvuurt, bv. /livefire/go/intro

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
