"""Engine status-registry. Iedere engine meldt zich hier aan met status
(OK / fout / niet-beschikbaar) zodat de Help → Engine-status dialog en de
statusbar altijd een up-to-date overzicht hebben."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineStatus:
    name: str
    available: bool
    detail: str = ""       # vrije tekst — bv. device-naam of foutmelding
    short: str = ""        # korte afkorting voor in de statusbar ("audio")


_registry: dict[str, EngineStatus] = {}


def register(status: EngineStatus) -> None:
    _registry[status.name] = status


def all_statuses() -> list[EngineStatus]:
    return list(_registry.values())


def get(name: str) -> EngineStatus | None:
    return _registry.get(name)


def failed_shortnames() -> list[str]:
    """Voor in de statusbar: lijst van korte engine-namen die niet werken."""
    return [s.short for s in _registry.values() if not s.available and s.short]
