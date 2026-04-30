"""Autosave: schrijft de workspace periodiek naar een sidecar-bestand
zodat een onverwachte exit niet alle voorbereidingswerk wegblaast.

Strategie:
  - Genoemde workspace ``foo.livefire`` → autosave naar ``foo.livefire.autosave``
    naast het origineel.
  - Onbenoemde (Untitled) workspace → autosave naar
    ``%APPDATA%\\liveFire\\autosave\\untitled-<sessionid>.livefire.autosave``.
    Sessie-id is een hex-string die per app-start uniek is, zodat twee
    parallelle sessies (één na de ander, na een crash) elkaar niet over-
    schrijven.
  - Schrijven gebeurt atomair: temp-file → ``os.replace`` → final.
    Dat voorkomt half-geschreven JSON tijdens een power-cut precies
    op een schrijf-tick.
  - Bij een succesvolle handmatige Save (action_save) verdwijnt het
    autosave-bestand — dan is het niet meer nodig.
  - Bij startup checkt MainWindow ``find_recoverable`` en biedt de
    operator de autosave aan om te herstellen.

Niet-doelen:
  - Geen versionering / history van autosaves. We willen één 'last known
    good', niet een tijdlijn.
  - Geen lock-file. Dubbele instances worden al door QSharedMemory in
    __main__.py geweigerd, dus wedijver om dezelfde autosave is
    onmogelijk.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QStandardPaths, QTimer

from .workspace import Workspace


# Default-interval — 30s is de QLab-conventie en geeft een goede
# balans tussen "weinig werk verloren" en "geen storend disk-flush
# tijdens een lopende cue". Override via constructor voor tests.
DEFAULT_INTERVAL_MS = 30_000

AUTOSAVE_SUFFIX = ".autosave"  # achter ``.livefire``: ``foo.livefire.autosave``


# ---- pad-helpers -----------------------------------------------------------

def _untitled_dir() -> Path:
    """Map waar autosaves van onbenoemde workspaces in landen.
    Aanmaken als die nog niet bestaat."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not base:
        base = str(Path.home() / ".livefire")
    p = Path(base) / "autosave"
    p.mkdir(parents=True, exist_ok=True)
    return p


def autosave_path_for(workspace_path: Path | None, session_id: str) -> Path:
    """Bepaal het autosave-pad voor een workspace.

    - Genoemde workspace → naast het origineel: ``foo.livefire.autosave``.
    - Onbenoemde workspace → in de app-autosave-map met de sessie-id
      verwerkt zodat parallelle sessies elkaar niet overschrijven.
    """
    if workspace_path is not None:
        return workspace_path.with_name(workspace_path.name + AUTOSAVE_SUFFIX)
    return _untitled_dir() / f"untitled-{session_id}.livefire{AUTOSAVE_SUFFIX}"


# ---- atomic write ----------------------------------------------------------

def _atomic_write_json(path: Path, payload: dict) -> None:
    """Serialiseer ``payload`` naar ``path`` zonder een half-geschreven
    bestand achter te laten als het proces midden in de schrijf wordt
    afgebroken.

    Werkwijze: schrijf naar ``path.tmp``, ``flush``+``fsync`` (zodat de
    pagina's écht op disk staan, niet alleen in OS-cache), dan
    ``os.replace`` — dat is een atomaire rename op zowel POSIX als
    Windows (NTFS) wanneer source en target op hetzelfde volume staan.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # fsync kan op sommige FS (netwerk-mount, tmpfs) onbeschik-
            # baar zijn — niet fataal, atomair-replace is nog steeds
            # ons voornaamste vangnet.
            pass
    os.replace(tmp, path)


# ---- recovery ---------------------------------------------------------------

class RecoverableAutosave:
    """Beschrijft een gevonden autosave die nieuwer is dan z'n bron-
    workspace, of een onbenoemde autosave uit een gecrashte sessie.
    Bevat alle info die de UI nodig heeft om de operator een keuze
    voor te leggen."""

    __slots__ = ("autosave_path", "original_path", "is_untitled")

    def __init__(
        self,
        autosave_path: Path,
        original_path: Path | None,
        is_untitled: bool,
    ) -> None:
        self.autosave_path = autosave_path
        self.original_path = original_path
        self.is_untitled = is_untitled


def find_recoverable_for(workspace_path: Path) -> RecoverableAutosave | None:
    """Bij ``Open ...``: is er een autosave-bestand naast deze workspace
    dat nieuwer is dan de workspace zelf? Zo ja → de operator kan kiezen
    om die autosave te laden in plaats van de oudere on-disk versie.
    """
    autosave = workspace_path.with_name(workspace_path.name + AUTOSAVE_SUFFIX)
    if not autosave.is_file():
        return None
    try:
        if autosave.stat().st_mtime <= workspace_path.stat().st_mtime:
            # Autosave is ouder of even oud → niets te recoveren.
            return None
    except OSError:
        return None
    return RecoverableAutosave(
        autosave_path=autosave,
        original_path=workspace_path,
        is_untitled=False,
    )


def find_orphan_untitled() -> list[RecoverableAutosave]:
    """Bij startup: zoek alle ``untitled-*.livefire.autosave``-bestanden
    uit eerdere sessies (de huidige sessie heeft z'n bestand pas later
    aangemaakt, dus die zit hier nog niet bij). Geef de gevonden
    bestanden terug, jongste eerst — dan kan de operator de meest
    recente makkelijk pakken."""
    folder = _untitled_dir()
    found: list[Path] = []
    for p in folder.glob(f"untitled-*.livefire{AUTOSAVE_SUFFIX}"):
        if p.is_file():
            found.append(p)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        RecoverableAutosave(autosave_path=p, original_path=None, is_untitled=True)
        for p in found
    ]


# ---- manager ---------------------------------------------------------------

class AutosaveManager(QObject):
    """Beheert het schrijven van autosaves voor één MainWindow-instance.

    Gebruik:
        am = AutosaveManager(window)
        am.start()                  # tikt iedere 30s
        am.bump()                   # forceer een save direct (bv. na GO)
        am.attach_workspace(ws)     # bij New / Open
        am.clear_for_current()      # bij succesvolle Save
        am.stop()                   # bij app-exit

    De manager raakt de Workspace zelf nooit aan — hij snapshot 'm enkel
    via ``ws.to_dict()``. Daardoor is er geen risico dat autosave de
    dirty-flag of path van de échte workspace verandert.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        interval_ms: int = DEFAULT_INTERVAL_MS,
        path_resolver: Callable[[Workspace, str], Path] | None = None,
    ) -> None:
        super().__init__(parent)
        # Sessie-id wordt eenmalig per AutosaveManager gegenereerd. Voor
        # tests injecteerbaar via ``self.session_id = ...`` na constructor.
        self.session_id = secrets.token_hex(4)
        self._workspace: Workspace | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)
        # Custom resolver maakt unit-tests makkelijker (tmpdir-paden).
        self._path_resolver = path_resolver or (
            lambda ws, sid: autosave_path_for(ws.path, sid)
        )
        # Het laatst-geschreven pad. Bewaard zodat we 'm bij rename
        # (Save As naar nieuwe locatie) of clear_for_current netjes
        # kunnen verwijderen.
        self._last_written: Path | None = None

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def attach_workspace(self, ws: Workspace) -> None:
        """Wissel de workspace die bewaakt wordt. Eerdere autosave (van
        de vorige workspace) wordt niet automatisch opgeruimd — die
        staat naast z'n oorspronkelijke bestand en blijft zinvol als
        recovery-baken voor de volgende keer dat dat bestand geopend
        wordt."""
        self._workspace = ws
        self._last_written = None

    def bump(self) -> None:
        """Schrijf nu, los van de timer-cyclus. Aanroepen na elke
        succesvolle GO zodat de meest recente cuelist-volgorde wordt
        vastgelegd."""
        self._tick()

    # ---- write ------------------------------------------------------------

    def _tick(self) -> None:
        ws = self._workspace
        if ws is None:
            return
        # Niets te doen als er sinds de laatste save geen wijzigingen
        # zijn — bespaart disk I/O én verlengt SSD-leven op show-PCs
        # die de hele dag aanstaan.
        if not ws.dirty and self._last_written is not None:
            return
        target = self._path_resolver(ws, self.session_id)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(target, ws.to_dict())
        except Exception:  # noqa: BLE001 — autosave-failure mag de app niet kelderen
            # Stil falen. Het echte vangnet is dat de operator nog
            # steeds handmatig kan saven; we willen geen modal pop-up
            # tijdens een lopende show.
            return
        self._last_written = target

    # ---- cleanup ----------------------------------------------------------

    def clear_for_current(self) -> None:
        """Verwijder het autosave-bestand van de huidige workspace.
        Aan te roepen na een succesvolle handmatige Save — dan is de
        on-disk workspace zelf weer de waarheid en dragen we geen
        stale autosave mee."""
        ws = self._workspace
        if ws is None:
            return
        candidate = self._path_resolver(ws, self.session_id)
        try:
            if candidate.is_file():
                candidate.unlink()
        except OSError:
            pass
        # En ook de tmp-file als die per ongeluk bleef hangen.
        tmp = candidate.with_suffix(candidate.suffix + ".tmp")
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        self._last_written = None
