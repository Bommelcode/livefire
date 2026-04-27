"""Undo/redo via Qt's QUndoStack + QUndoCommand-subklassen.

Iedere mutatie op een Workspace gaat via één van de Cmd-klassen hier,
zodat:

* Edit → Undo / Redo (Ctrl+Z / Ctrl+Y) iedere actie netjes terugdraait.
* Inspector-edits op hetzelfde veld + dezelfde cue-set binnen één edit-
  sessie via ``mergeWith`` als één undo-stap tellen — anders zou je per
  spinbox-tick of toetsaanslag een nieuwe undo-entry krijgen.

Architectuur
------------
De commands muteren puur data (Workspace, Cue) en roepen via de
``RefreshHook`` callbacks in MainWindow aan om de UI bij te werken.
Dat houdt deze module Qt-widget-vrij behalve QUndoCommand zelf.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from PyQt6.QtGui import QUndoCommand

from .cues import Cue
from .workspace import Workspace


@dataclass
class RefreshHook:
    """Callbacks die MainWindow inschiet zodat commands de UI kunnen
    laten verversen zonder de QWidget-tree zelf aan te raken.

    * ``on_struct`` — cuelist-volgorde of -inhoud is gewijzigd
      (add/remove/move/renumber). MainWindow doet typisch een
      ``cue_list.refresh()`` + inspector-revalidate + title-sync.
    * ``on_field(cue_id)`` — één veld op één cue is gewijzigd.
      MainWindow doet typisch ``cue_list.update_cue_display(cue_id)``
      + inspector-resync als 'ie deze cue toont.
    """

    on_struct: Callable[[], None]
    on_field: Callable[[str], None]


# ---- structurele commands --------------------------------------------------


class AddCueCmd(QUndoCommand):
    """Voeg één cue in op een specifieke index. Undo verwijdert 'm."""

    def __init__(
        self,
        ws: Workspace,
        cue: Cue,
        index: int | None,
        hook: RefreshHook,
        label: str = "Add cue",
    ):
        super().__init__(label)
        self.ws = ws
        self.cue = cue
        # Resolve index nu — anders kan undo bij een gemute volgorde 'm
        # op de verkeerde plek terugzetten.
        self.index = len(ws.cues) if (index is None or index >= len(ws.cues)) else index
        self.hook = hook

    def redo(self) -> None:
        self.ws.add_cue(self.cue, index=self.index)
        self.hook.on_struct()

    def undo(self) -> None:
        self.ws.remove_cue(self.cue.id)
        self.ws.dirty = True
        self.hook.on_struct()


class RemoveCuesCmd(QUndoCommand):
    """Atomische delete van één of meerdere cues. Snapshot bewaart de
    originele index per cue zodat undo ze op de juiste plek terugzet."""

    def __init__(self, ws: Workspace, cues: Iterable[Cue], hook: RefreshHook):
        cues_list = list(cues)
        super().__init__(
            f"Delete {len(cues_list)} cue(s)" if len(cues_list) != 1 else "Delete cue"
        )
        self.ws = ws
        self.hook = hook
        # Sorteer op index zodat undo in oplopende volgorde insert — bij
        # dezelfde volgorde komen de cues weer op precies dezelfde plek.
        self._snapshot: list[tuple[int, Cue]] = sorted(
            ((ws.index_of(c.id), c) for c in cues_list),
            key=lambda t: t[0],
        )

    def redo(self) -> None:
        for _, c in self._snapshot:
            self.ws.remove_cue(c.id)
        self.ws.dirty = True
        self.hook.on_struct()

    def undo(self) -> None:
        for idx, c in self._snapshot:
            self.ws.add_cue(c, index=idx)
        self.ws.dirty = True
        self.hook.on_struct()


class MoveCueCmd(QUndoCommand):
    """Verplaats één cue met ``delta`` (±1). Multi-cue moves doe je via
    een macro op de QUndoStack."""

    def __init__(self, ws: Workspace, cue_id: str, delta: int, hook: RefreshHook):
        super().__init__("Move cue")
        self.ws = ws
        self.cue_id = cue_id
        self.delta = delta
        self.hook = hook

    def redo(self) -> None:
        if self.ws.move(self.cue_id, self.delta):
            self.hook.on_struct()

    def undo(self) -> None:
        if self.ws.move(self.cue_id, -self.delta):
            self.hook.on_struct()


class RenumberCmd(QUndoCommand):
    """Hernummer alle cues; undo herstelt de oude cue_number-strings."""

    def __init__(self, ws: Workspace, hook: RefreshHook, start: int = 1, step: int = 1):
        super().__init__("Renumber cues")
        self.ws = ws
        self.start = start
        self.step = step
        self.hook = hook
        self._old_numbers: dict[str, str] = {c.id: c.cue_number for c in ws.cues}

    def redo(self) -> None:
        self.ws.renumber(start=self.start, step=self.step)
        self.hook.on_struct()

    def undo(self) -> None:
        for c in self.ws.cues:
            if c.id in self._old_numbers:
                c.cue_number = self._old_numbers[c.id]
        self.ws.dirty = True
        self.hook.on_struct()


# ---- veld-mutatie ---------------------------------------------------------


class ReparentCuesCmd(QUndoCommand):
    """Verplaats een set cues naar een andere parent_group_id, en zet ze
    direct na de target-group (of aan het einde van de cuelist als de
    target leeg is). Snapshot bewaart oude parent + index per cue zodat
    undo netjes alles terugzet.

    Wordt gebruikt door cuelist's "Move into group" / "Move out of group"
    context-menu en door drag-drop bij het verplaatsen van children
    in/uit een group.
    """

    def __init__(
        self,
        ws: Workspace,
        cue_ids: Iterable[str],
        new_parent_id: str,
        hook: RefreshHook,
    ):
        ids = list(cue_ids)
        super().__init__(
            f"Move {len(ids)} cue(s) into group" if new_parent_id else
            f"Move {len(ids)} cue(s) out of group"
        )
        self.ws = ws
        self.cue_ids = ids
        self.new_parent_id = new_parent_id
        self.hook = hook
        # Snapshot oude parent + positie van iedere cue
        self._old_state: list[tuple[str, str, int]] = []
        for cid in ids:
            cue = ws.find(cid)
            if cue is None:
                continue
            self._old_state.append(
                (cid, cue.parent_group_id, ws.index_of(cid))
            )

    def redo(self) -> None:
        # Werk in volgorde van huidige index zodat verplaatsing stabiel is.
        ids_sorted = sorted(self.cue_ids, key=lambda c: self.ws.index_of(c))
        for cid in ids_sorted:
            cue = self.ws.find(cid)
            if cue is None:
                continue
            cue.parent_group_id = self.new_parent_id
            # Plaats de cue direct ná het einde van de target-group, of
            # aan het einde van de cuelist als top-level.
            self._move_to_logical_position(cid)
        self.ws.dirty = True
        self.hook.on_struct()

    def undo(self) -> None:
        # Iterate in reverse zodat we de snapshot-volgorde herstellen.
        for cid, old_parent, old_idx in reversed(self._old_state):
            cue = self.ws.find(cid)
            if cue is None:
                continue
            cue.parent_group_id = old_parent
            cur = self.ws.index_of(cid)
            if cur < 0:
                continue
            target = max(0, min(old_idx, len(self.ws.cues) - 1))
            popped = self.ws.cues.pop(cur)
            self.ws.cues.insert(target, popped)
        self.ws.dirty = True
        self.hook.on_struct()

    def _move_to_logical_position(self, cue_id: str) -> None:
        """Verplaats cue_id zodat 'ie direct na de parent-group + diens
        bestaande descendants komt. Houdt de cuelist-volgorde consistent
        met de tree-rendering."""
        if not self.new_parent_id:
            # Move-out: zet aan het einde van de cuelist. Eenvoudigste
            # invariant; alternatief is "direct na de oorspronkelijke
            # parent-group" maar dat botst als meerdere cues uit
            # verschillende groups tegelijk eruit gaan.
            cur = self.ws.index_of(cue_id)
            if cur < 0:
                return
            popped = self.ws.cues.pop(cur)
            self.ws.cues.append(popped)
            return
        # Insert positie = direct na de laatste descendant van de target-
        # group, of direct na de target-group zelf als die nog leeg is.
        target_end = self.ws.first_index_after_group(self.new_parent_id)
        cur = self.ws.index_of(cue_id)
        if cur < 0:
            return
        popped = self.ws.cues.pop(cur)
        # Na de pop kan target_end één positie zijn opgeschoven.
        if cur < target_end:
            target_end -= 1
        self.ws.cues.insert(target_end, popped)


class SetCueFieldCmd(QUndoCommand):
    """Wijzig één veld op één of meerdere cues.

    Achtereenvolgende edits op dezelfde (cue-set, veld)-combinatie worden
    door ``mergeWith`` samengevoegd zodat je niet per spinbox-tick of
    toetsaanslag een nieuwe undo-entry krijgt. De originele
    ``_old_values`` blijven bewaard zodat één undo terugspringt naar de
    waarde van vóór de hele edit-burst.
    """

    _ID = 1001

    def __init__(
        self,
        ws: Workspace,
        cue_ids: Iterable[str],
        field: str,
        new_value: Any,
        hook: RefreshHook,
    ):
        ids = list(cue_ids)
        super().__init__(f"Set {field}")
        self.ws = ws
        self.cue_ids = ids
        self.field = field
        self.new_value = new_value
        self.hook = hook
        # Snapshot oude waarden vóór de eerste apply.
        self._old_values: dict[str, Any] = {}
        for cid in ids:
            cue = ws.find(cid)
            if cue is not None:
                self._old_values[cid] = getattr(cue, field, None)

    def id(self) -> int:
        return self._ID

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetCueFieldCmd):
            return False
        if other.field != self.field:
            return False
        if set(other.cue_ids) != set(self.cue_ids):
            return False
        # Neem de nieuwste new_value over; oude _old_values blijft staan
        # (= de waarde van vóór de allereerste edit in de burst).
        self.new_value = other.new_value
        return True

    def redo(self) -> None:
        for cid in self.cue_ids:
            cue = self.ws.find(cid)
            if cue is not None:
                setattr(cue, self.field, self.new_value)
        self.ws.dirty = True
        for cid in self.cue_ids:
            self.hook.on_field(cid)

    def undo(self) -> None:
        for cid, old in self._old_values.items():
            cue = self.ws.find(cid)
            if cue is not None:
                setattr(cue, self.field, old)
        self.ws.dirty = True
        for cid in self.cue_ids:
            self.hook.on_field(cid)
