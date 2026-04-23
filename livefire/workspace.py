"""Workspace IO. Leest en schrijft .livefire bestanden (JSON), met
format_version-aware migratiepad."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import WORKSPACE_FORMAT_VERSION, APP_VERSION
from .cues import Cue, CueType


@dataclass
class Workspace:
    """Bevat alle cues en workspace-metadata."""

    cues: list[Cue] = field(default_factory=list)
    name: str = "Untitled"
    path: Path | None = None
    dirty: bool = False

    # ---- cue-beheer --------------------------------------------------------

    def add_cue(self, cue: Cue, index: int | None = None) -> None:
        if index is None or index >= len(self.cues):
            self.cues.append(cue)
        else:
            self.cues.insert(index, cue)
        self.dirty = True

    def remove_cue(self, cue_id: str) -> Cue | None:
        for i, c in enumerate(self.cues):
            if c.id == cue_id:
                self.dirty = True
                return self.cues.pop(i)
        return None

    def find(self, cue_id: str) -> Cue | None:
        return next((c for c in self.cues if c.id == cue_id), None)

    def index_of(self, cue_id: str) -> int:
        for i, c in enumerate(self.cues):
            if c.id == cue_id:
                return i
        return -1

    def move(self, cue_id: str, delta: int) -> bool:
        i = self.index_of(cue_id)
        j = i + delta
        if i < 0 or j < 0 or j >= len(self.cues):
            return False
        self.cues[i], self.cues[j] = self.cues[j], self.cues[i]
        self.dirty = True
        return True

    def renumber(self, start: int = 1, step: int = 1) -> None:
        """Hernummer cues oplopend — UX-convenience zoals QLab's
        'Renumber Selected Cues'."""
        n = start
        for c in self.cues:
            c.cue_number = str(n)
            n += step
        self.dirty = True

    # ---- serialisatie ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "format_version": WORKSPACE_FORMAT_VERSION,
            "app_version": APP_VERSION,
            "name": self.name,
            "cues": [c.to_dict() for c in self.cues],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        data = _migrate(data)
        ws = cls(name=data.get("name", "Untitled"))
        for cd in data.get("cues", []):
            ws.cues.append(Cue.from_dict(cd))
        return ws

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ValueError("Geen pad opgegeven om naar te saven.")
        target = Path(target)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.path = target
        self.dirty = False
        return target

    @classmethod
    def load(cls, path: Path) -> "Workspace":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        ws = cls.from_dict(data)
        ws.path = path
        ws.dirty = False
        return ws


# ---- migratiefuncties ------------------------------------------------------

def _migrate(data: dict) -> dict:
    """Accepteert een dict met mogelijk oudere format_version en geeft een
    dict terug dat aan de huidige WORKSPACE_FORMAT_VERSION voldoet.

    Migratieregels per stap zijn expliciet zodat we oude .livefire files altijd
    kunnen lezen zonder dat gebruikers hun workspaces opnieuw moeten opbouwen.
    """
    v = data.get("format_version", 1)

    # v1 (v0.2.x): enkele cues-array, geen video-fields (die gaan in v0.6)
    if v == 1:
        # v1 -> v2 is een no-op voor data; we markeren enkel de versie.
        # v2 introduceert de expliciete 'Stop all' target_cue_id=="" conventie
        # en fade_target_db ipv fade_volume_db rename.
        for c in data.get("cues", []):
            if "fade_volume_db" in c and "fade_target_db" not in c:
                c["fade_target_db"] = c.pop("fade_volume_db")
        v = 2

    # v2 is huidig
    if v != WORKSPACE_FORMAT_VERSION:
        raise ValueError(
            f"Onbekende workspace-versie {v}; deze liveFire kent t/m v{WORKSPACE_FORMAT_VERSION}."
        )
    data["format_version"] = WORKSPACE_FORMAT_VERSION
    return data
