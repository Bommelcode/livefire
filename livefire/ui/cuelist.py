"""Cue-list widget. Toont alle cues als regels met kolommen:
nr / type / naam / duur / continue / status."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyle, QComboBox,
)

from ..cues import Cue, CueType, ContinueMode
from ..i18n import t
from ..workspace import Workspace
from .style import STATE_COLORS, ACCENT, TEXT_DIM, tint_for_row


def _columns() -> list[str]:
    return [t("col.nr"), t("col.type"), t("col.name"),
            t("col.duration"), t("col.continue"), t("col.state")]


COLUMNS = _columns()
_COL_CONTINUE = 4


class _CueRowDelegate(QStyledItemDelegate):
    """Schildert zelf de per-cel BackgroundRole-brush. Nodig omdat Qt's
    stylesheet voor ``QTreeWidget::item`` (padding/border) normaal
    ``QTreeWidgetItem.setBackground()`` negeert."""

    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(bg, QBrush) and bg.color().alpha() > 0:
            if not (option.state & QStyle.StateFlag.State_Selected):
                painter.save()
                painter.fillRect(option.rect, bg)
                painter.restore()
        super().paint(painter, option, index)


class _ContinueDelegate(QStyledItemDelegate):
    """Inline-editor voor de Continue-kolom: opent een QComboBox met de
    drie ContinueMode-keuzes ipv het standaard tekstveld. Schrijft direct
    terug naar het Cue-object via de parent-CueListWidget en triggert
    een refresh-signaal voor de inspector + title."""

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        for mode in (ContinueMode.DO_NOT_CONTINUE,
                     ContinueMode.AUTO_CONTINUE,
                     ContinueMode.AUTO_FOLLOW):
            cb.addItem(ContinueMode.label(mode), mode)
        return cb

    def setEditorData(self, editor: QComboBox, index) -> None:
        # Lees de huidige cue.continue_mode, niet de cell-tekst — labels
        # zijn taalafhankelijk en kunnen mismatch geven.
        tree = self.parent()
        item = tree.topLevelItem(index.row())
        if item is None:
            return
        cue_id = item.data(0, Qt.ItemDataRole.UserRole)
        cue = tree.workspace.find(cue_id)
        if cue is None:
            return
        for i in range(editor.count()):
            if editor.itemData(i) == cue.continue_mode:
                editor.setCurrentIndex(i)
                # Open de dropdown direct zodat de operator één klik
                # nodig heeft ipv eerst het editor-veld zien openen.
                editor.showPopup()
                return

    def setModelData(self, editor: QComboBox, model, index) -> None:
        tree = self.parent()
        item = tree.topLevelItem(index.row())
        if item is None:
            return
        clicked_cue_id = item.data(0, Qt.ItemDataRole.UserRole)
        new_mode = int(editor.currentData())

        # Multi-select: als de geklikte cue onderdeel is van een grotere
        # selectie, wijzig dan álle geselecteerde cues. Anders alleen
        # deze ene. Dit komt overeen met hoe inspector-bulk-edits ook
        # over de selectie heen werken.
        selected_ids = {c.id for c in tree.selected_cues()}
        target_ids = selected_ids if clicked_cue_id in selected_ids else {clicked_cue_id}

        # Filter cues die al op de gevraagde waarde staan — anders krijg
        # je een undo-entry zonder echte verandering.
        target_ids = {
            cid for cid in target_ids
            if (cue := tree.workspace.find(cid)) is not None
            and cue.continue_mode != new_mode
        }
        if not target_ids:
            return

        sink = getattr(tree, "command_sink", None)
        if sink is not None:
            sink.push_set_field(list(target_ids), "continue_mode", new_mode)
        else:
            # Fallback (tests): direct muteren.
            for cid in target_ids:
                cue = tree.workspace.find(cid)
                if cue is not None:
                    cue.continue_mode = new_mode
                    tree.update_cue_display(cid)
                    tree.cue_field_edited.emit(cid)
            tree.workspace.dirty = True

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)


def _fmt_duration(sec: float) -> str:
    if sec <= 0:
        return "—"
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


class CueListWidget(QTreeWidget):
    """Lijst van cues met selectie- en drag-reorder support."""

    cue_selected = pyqtSignal(object)     # Cue | None
    playhead_changed = pyqtSignal(int)
    go_requested = pyqtSignal()
    files_dropped = pyqtSignal(list)      # list[str] paden van gedropte bestanden
    cue_field_edited = pyqtSignal(str)    # cue_id — inline edit (bv. Continue-kolom)

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self._playhead_index = 0

        # Drag-and-drop van externe bestanden. We zetten alleen AcceptDrops
        # aan; DragEnabled laten we uit zodat QTreeWidget geen eigen interne
        # reorder-drag doet (Ctrl+↑/↓ en de toolbar-pijltjes zijn de enige
        # reorder-routes).
        self.setAcceptDrops(True)

        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(COLUMNS)
        # Tooltips per kolom-header (index == COLUMNS.index)
        _column_tooltips = [
            "Cue number — free text field, shown as a color bar when a color is set",
            "Cue type (Audio / Fade / Wait / Stop / Start / Group / Memo)",
            "Cue name — free text field",
            "Action duration (for Audio: set duration or — = play to end of file)",
            "Continue mode: Do Not Continue / Auto-Continue / Auto-Follow",
            "Runtime state: idle / running / finished",
        ]
        for i, tip in enumerate(_column_tooltips):
            self.headerItem().setToolTip(i, tip)
        self.setToolTip(
            "Cuelist — double-click to set the playhead and fire. "
            "Ctrl+↑/↓ moves selected cues."
        )
        self.setAlternatingRowColors(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        hdr = self.header()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Naam
        self.setColumnWidth(0, 60)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(3, 70)
        self.setColumnWidth(4, 120)
        self.setColumnWidth(5, 80)

        self.setItemDelegate(_CueRowDelegate(self))
        # Inline-editor (combobox) op de Continue-kolom. Een kolom-
        # specifieke delegate overschrijft de algemene _CueRowDelegate
        # alleen voor die kolom, dus de cue-color-tint blijft elders
        # werken.
        self.setItemDelegateForColumn(_COL_CONTINUE, _ContinueDelegate(self))

        self.itemSelectionChanged.connect(self._on_selection)
        self.itemDoubleClicked.connect(self._on_double_click)

        self.refresh()

    # ---- data --------------------------------------------------------------

    def refresh(self) -> None:
        sel_ids = [c.id for c in self.selected_cues()]
        self.clear()
        for i, cue in enumerate(self.workspace.cues):
            item = self._make_item(cue, i)
            self.addTopLevelItem(item)
        # Herstel selectie
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            cue_id = item.data(0, Qt.ItemDataRole.UserRole)
            if cue_id in sel_ids:
                item.setSelected(True)
        self._apply_playhead_style()

    def _make_item(self, cue: Cue, index: int) -> QTreeWidgetItem:
        if cue.cue_type == CueType.VIDEO:
            # Trim bepaalt effectieve duur:
            # (end - start) als end > 0, anders (file_duration - start) als de
            # preview 'm gecachet heeft, anders user-set cue.duration.
            if cue.video_end_offset > 0:
                dur_value = max(0.0, cue.video_end_offset - cue.video_start_offset)
            elif cue.video_file_duration > 0:
                dur_value = max(0.0, cue.video_file_duration - cue.video_start_offset)
            else:
                dur_value = cue.duration
        elif cue.cue_type == CueType.WAIT:
            dur_value = cue.wait_duration
        else:
            dur_value = cue.duration
        item = QTreeWidgetItem([
            cue.cue_number or str(index + 1),
            t(f"cuetype.{cue.cue_type}"),
            cue.name or "(untitled)",
            _fmt_duration(dur_value),
            ContinueMode.label(cue.continue_mode),
            t(f"state.{cue.state}"),
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, cue.id)
        # Editable-flag is voorwaarde voor de inline Continue-dropdown.
        # mousePressEvent staart de edit() alleen voor kolom 4, dus
        # andere kolommen openen geen editor ondanks deze flag.
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        # Kleur status-cel
        color = STATE_COLORS.get(cue.state, QColor("#888"))
        item.setForeground(5, QBrush(color))
        # Cue-color tag: volle kleur als balk op nummer-kolom, lichte tint over
        # de rest zodat de regel direct als gekleurde cue herkenbaar is.
        if cue.color:
            full = QBrush(QColor(cue.color))
            tint = QBrush(tint_for_row(cue.color))
            item.setBackground(0, full)
            for col in range(1, len(COLUMNS)):
                item.setBackground(col, tint)
        return item

    def update_cue(self, cue_id: str) -> None:
        """Update één regel zonder alles te herbouwen — voor state-changes."""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == cue_id:
                cue = self.workspace.find(cue_id)
                if cue is None:
                    return
                item.setText(5, t(f"state.{cue.state}"))
                color = STATE_COLORS.get(cue.state, QColor("#888"))
                item.setForeground(5, QBrush(color))
                return

    def update_cue_display(self, cue_id: str) -> None:
        """Update álle zichtbare kolommen van één cue zonder clear/rebuild.
        Gebruikt door de inspector zodat keyboard-focus op spinboxen niet
        verspringt als de gebruiker waardes aanpast."""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) != cue_id:
                continue
            cue = self.workspace.find(cue_id)
            if cue is None:
                return
            # Duur (zelfde logica als _make_item)
            if cue.cue_type == CueType.VIDEO:
                if cue.video_end_offset > 0:
                    dur_value = max(0.0, cue.video_end_offset - cue.video_start_offset)
                elif cue.video_file_duration > 0:
                    dur_value = max(0.0, cue.video_file_duration - cue.video_start_offset)
                else:
                    dur_value = cue.duration
            elif cue.cue_type == CueType.WAIT:
                dur_value = cue.wait_duration
            else:
                dur_value = cue.duration
            item.setText(0, cue.cue_number or str(i + 1))
            item.setText(1, t(f"cuetype.{cue.cue_type}"))
            item.setText(2, cue.name or "(untitled)")
            item.setText(3, _fmt_duration(dur_value))
            item.setText(4, ContinueMode.label(cue.continue_mode))
            item.setText(5, t(f"state.{cue.state}"))
            state_color = STATE_COLORS.get(cue.state, QColor("#888"))
            item.setForeground(5, QBrush(state_color))
            # Kleur-balk bijwerken
            if cue.color:
                full = QBrush(QColor(cue.color))
                tint = QBrush(tint_for_row(cue.color))
                item.setBackground(0, full)
                for col in range(1, len(COLUMNS)):
                    item.setBackground(col, tint)
            else:
                empty = QBrush()
                for col in range(len(COLUMNS)):
                    item.setBackground(col, empty)
            return

    # ---- selectie & playhead ----------------------------------------------

    def selected_cues(self) -> list[Cue]:
        out: list[Cue] = []
        for item in self.selectedItems():
            cue_id = item.data(0, Qt.ItemDataRole.UserRole)
            cue = self.workspace.find(cue_id)
            if cue is not None:
                out.append(cue)
        return out

    def select_cue(self, cue_id: str) -> None:
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == cue_id:
                # ExtendedSelection: setCurrentItem alléén zet hem niet als
                # geselecteerd. Voor keyboard-navigatie en ons playhead-from-
                # selection-mechanisme moet de selectie ook echt op dit item.
                self.clearSelection()
                item.setSelected(True)
                self.setCurrentItem(item)
                return

    def set_playhead(self, index: int) -> None:
        new_idx = max(0, min(index, len(self.workspace.cues)))
        if new_idx == self._playhead_index:
            return
        self._playhead_index = new_idx
        self._apply_playhead_style()
        self.playhead_changed.emit(self._playhead_index)

    def _apply_playhead_style(self) -> None:
        dim = QBrush(QColor(TEXT_DIM))
        accent = QBrush(QColor(ACCENT))
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            f = item.font(0)
            f.setBold(i == self._playhead_index)
            for col in range(self.columnCount()):
                item.setFont(col, f)
            item.setForeground(1, accent if i == self._playhead_index else dim)

    # ---- events ------------------------------------------------------------

    def _on_selection(self) -> None:
        cues = self.selected_cues()
        self.cue_selected.emit(cues[0] if cues else None)
        # QLab-gedrag: selectie stuurt de playhead. Enkelklik / pijltjes zetten
        # de playhead zonder GO; dubbelklik blijft set_playhead + go_requested.
        if cues:
            idx = self.workspace.index_of(cues[0].id)
            if idx >= 0 and idx != self._playhead_index:
                self.set_playhead(idx)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        cue_id = item.data(0, Qt.ItemDataRole.UserRole)
        idx = self.workspace.index_of(cue_id)
        if idx >= 0:
            self.set_playhead(idx)
            self.go_requested.emit()

    def mousePressEvent(self, e):  # type: ignore[override]
        # Eerst de standaard selectie/playhead-routine. Daarna, als de
        # klik binnen de Continue-kolom valt, openen we expliciet de
        # editor (dropdown). EditTriggers staat globaal op NoEdit, dus
        # andere kolommen blijven niet-editable.
        super().mousePressEvent(e)
        idx = self.indexAt(e.position().toPoint())
        if idx.isValid() and idx.column() == _COL_CONTINUE:
            self.edit(idx)

    def keyPressEvent(self, e):
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if e.key() == Qt.Key.Key_Up:
                self.move_selected(-1)
                return
            if e.key() == Qt.Key.Key_Down:
                self.move_selected(1)
                return
            if e.key() == Qt.Key.Key_A:
                self.selectAll()
                return
        super().keyPressEvent(e)

    def move_selected(self, delta: int) -> None:
        cues = self.selected_cues()
        if not cues:
            return
        cues_sorted = sorted(cues, key=lambda c: self.workspace.index_of(c.id),
                             reverse=(delta > 0))
        sink = getattr(self, "command_sink", None)
        if sink is not None:
            # Multi-cue move = één macro op de undo-stack zodat één Ctrl+Z
            # alle moves van deze actie ongedaan maakt.
            sink.begin_macro("Move cue(s)" if len(cues_sorted) > 1 else "Move cue")
            try:
                for c in cues_sorted:
                    sink.push_move_cue(c.id, delta)
            finally:
                sink.end_macro()
        else:
            # Fallback (bv. tests zonder mainwindow): direct muteren.
            for c in cues_sorted:
                self.workspace.move(c.id, delta)
            self.refresh()

    # ---- drag-and-drop ----------------------------------------------------

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        md = e.mimeData()
        if not md.hasUrls():
            e.ignore()
            return
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if not paths:
            e.ignore()
            return
        e.acceptProposedAction()
        self.files_dropped.emit(paths)
