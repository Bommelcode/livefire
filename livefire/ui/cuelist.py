"""Cue-list widget. Toont alle cues als regels met kolommen:
nr / type / naam / duur / continue / status."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyle,
)

from ..cues import Cue, CueType, ContinueMode
from ..i18n import t
from ..workspace import Workspace
from .style import STATE_COLORS, ACCENT, TEXT_DIM, tint_for_row


def _columns() -> list[str]:
    return [t("col.nr"), t("col.type"), t("col.name"),
            t("col.duration"), t("col.continue"), t("col.state")]


COLUMNS = _columns()


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
            "Cue-nummer — vrij tekstveld, wordt zichtbaar als kleurbalk als er een kleur is ingesteld",
            "Cue-type (Audio / Fade / Wait / Stop / Start / Group / Memo)",
            "Naam van de cue — vrij tekstveld",
            "Actie-duur (voor Audio: ingestelde duration of — = speel tot einde bestand)",
            "Continue-mode: Do Not Continue / Auto-Continue / Auto-Follow",
            "Runtime-status: idle / running / finished",
        ]
        for i, tip in enumerate(_column_tooltips):
            self.headerItem().setToolTip(i, tip)
        self.setToolTip(
            "Cuelist — dubbelklik om playhead te zetten en te starten. "
            "Ctrl+↑/↓ verplaatst geselecteerde cues."
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
            cue.name or "(naamloos)",
            _fmt_duration(dur_value),
            ContinueMode.label(cue.continue_mode),
            t(f"state.{cue.state}"),
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, cue.id)
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
            item.setText(2, cue.name or "(naamloos)")
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
        self._playhead_index = max(0, min(index, len(self.workspace.cues)))
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
