"""Cue-list widget. Toont alle cues als regels met kolommen:
nr / type / naam / duur / continue / status."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyle, QComboBox, QMenu,
)

from ..cues import Cue, CueType, ContinueMode
from ..i18n import t
from ..workspace import Workspace
from .style import STATE_COLORS, ACCENT, ACCENT_ALT, TEXT_DIM, tint_for_row


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
        cb.setObjectName("continueEditor")
        for mode in (ContinueMode.DO_NOT_CONTINUE,
                     ContinueMode.AUTO_CONTINUE,
                     ContinueMode.AUTO_FOLLOW):
            cb.addItem(ContinueMode.label(mode), mode)
        # Stijl het editor-vlak met de cue-kleur. We doen 't op DRIE
        # manieren tegelijk omdat Qt-combobox styling notoir koppig is:
        # 1) Hoog-specifieke ID-selector (#continueEditor) overrult de
        #    globale stylesheet
        # 2) palette() voor 't geval Qt's native style 'n stylesheet
        #    negeert
        # 3) setAutoFillBackground zodat de bg-fill wordt getekend
        tree = self.parent()
        item = tree.itemFromIndex(index) if tree is not None else None
        cue_id = (
            item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        )
        cue = tree.workspace.find(cue_id) if cue_id and tree is not None else None
        if cue is not None and cue.color:
            base = QColor(cue.color)
            bg = base.darker(160)
            white = QColor("white")
            # Palette — onafhankelijk van stylesheet
            from PyQt6.QtGui import QPalette
            pal = cb.palette()
            for role in (
                QPalette.ColorRole.Base,
                QPalette.ColorRole.Button,
                QPalette.ColorRole.Window,
            ):
                pal.setColor(role, bg)
            for role in (
                QPalette.ColorRole.Text,
                QPalette.ColorRole.ButtonText,
                QPalette.ColorRole.WindowText,
            ):
                pal.setColor(role, white)
            cb.setPalette(pal)
            cb.setAutoFillBackground(True)
            # Stylesheet met ID-selector — hoogste specificity, sláát
            # de algemene QComboBox-rule uit style.py over.
            cb.setStyleSheet(
                f"QComboBox#continueEditor {{ "
                f"  background-color: {bg.name()}; "
                f"  color: white; "
                f"  border: 1px solid {base.name()}; "
                f"  padding: 1px 6px; "
                f"}} "
                f"QComboBox#continueEditor::drop-down {{ "
                f"  border: none; "
                f"  background-color: {bg.name()}; "
                f"}} "
                f"QComboBox#continueEditor QAbstractItemView {{ "
                f"  background-color: {bg.name()}; "
                f"  color: white; "
                f"  selection-background-color: {base.name()}; "
                f"  selection-color: white; "
                f"}}"
            )
        return cb

    def setEditorData(self, editor: QComboBox, index) -> None:
        # Lees de huidige cue.continue_mode, niet de cell-tekst — labels
        # zijn taalafhankelijk en kunnen mismatch geven.
        tree = self.parent()
        item = tree.itemFromIndex(index)
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
        item = tree.itemFromIndex(index)
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
        # Toon disclosure-arrows zodat group-cues zichtbaar uit/inklapbaar
        # zijn. Kleine indent zodat children niet ver verspringen op kleine
        # schermen.
        self.setRootIsDecorated(True)
        self.setIndentation(16)
        self.setUniformRowHeights(True)
        # cue-id → QTreeWidgetItem; refresh() vult 'm zodat lookups in
        # nested structures O(1) zijn (top-level + child-items).
        self._id_to_item: dict[str, QTreeWidgetItem] = {}
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

        # Context-menu voor "Move into group" / "Move out of group" en
        # eventuele toekomstige cuelist-acties.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.refresh()

    # ---- data --------------------------------------------------------------

    def refresh(self) -> None:
        sel_ids = [c.id for c in self.selected_cues()]
        # Onthoud expand-state per group-id zodat refresh een group niet
        # ineens dichtklapt na elke add/remove/move.
        prev_expanded: set[str] = {
            cid for cid, item in self._id_to_item.items() if item.isExpanded()
        }
        self.clear()
        self._id_to_item = {}
        # Itereer in workspace-volgorde — children komen direct na hun
        # parent omdat workspace-volgorde dat afdwingt (zie move-into-
        # group / move-out-of-group). Een child gaat onder z'n parent-
        # item; cues zonder parent gaan top-level.
        for i, cue in enumerate(self.workspace.cues):
            item = self._make_item(cue, i)
            self._id_to_item[cue.id] = item
            if cue.parent_group_id and cue.parent_group_id in self._id_to_item:
                self._id_to_item[cue.parent_group_id].addChild(item)
            else:
                self.addTopLevelItem(item)
            if cue.cue_type == CueType.GROUP:
                # Default: expanded zodat een nieuwe group meteen z'n
                # children laat zien. Daarna onthouden we de keuze van
                # de operator via prev_expanded.
                item.setExpanded(cue.id in prev_expanded or not prev_expanded)
        # Herstel selectie via de id-map (werkt voor nested items).
        for cue_id in sel_ids:
            item = self._id_to_item.get(cue_id)
            if item is not None:
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
        item = self._id_to_item.get(cue_id)
        if item is None:
            return
        cue = self.workspace.find(cue_id)
        if cue is None:
            return
        item.setText(5, t(f"state.{cue.state}"))
        color = STATE_COLORS.get(cue.state, QColor("#888"))
        item.setForeground(5, QBrush(color))

    def update_cue_display(self, cue_id: str) -> None:
        """Update álle zichtbare kolommen van één cue zonder clear/rebuild.
        Gebruikt door de inspector zodat keyboard-focus op spinboxen niet
        verspringt als de gebruiker waardes aanpast."""
        item = self._id_to_item.get(cue_id)
        if item is None:
            return
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
        idx = self.workspace.index_of(cue_id)
        item.setText(0, cue.cue_number or str(idx + 1))
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
        # Playhead-stijl re-applyen zodat de ▶-marker + bg-wash overleven
        # na 'n veld-update (anders raakt 'ie weg bij elke nummer-edit).
        self._apply_playhead_style()

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
        item = self._id_to_item.get(cue_id)
        if item is None:
            return
        # ExtendedSelection: setCurrentItem alléén zet 'm niet als
        # geselecteerd. Voor keyboard-navigatie en ons playhead-from-
        # selection-mechanisme moet de selectie ook echt op dit item.
        self.clearSelection()
        item.setSelected(True)
        self.setCurrentItem(item)
        # Als 't item een nested child is, vouw alle parent-groups open
        # zodat de operator hem ziet.
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    def set_playhead(self, index: int) -> None:
        new_idx = max(0, min(index, len(self.workspace.cues)))
        if new_idx == self._playhead_index:
            return
        self._playhead_index = new_idx
        self._apply_playhead_style()
        self.playhead_changed.emit(self._playhead_index)

    def _apply_playhead_style(self) -> None:
        """Markeer de cue waar de playhead op staat. Tweelagige aanpak:

        1) ▶-marker in de nummer-cel (wit, dik) — werkt zelfs op een
           cue met dezelfde kleur als de oude oranje accent-bar (klassieke
           verwarring: oranje-cue + oranje-bar = onzichtbaar)
        2) Witte 1px-rand om de hele rij + iets oplichtende bg — tint
           houden we klein zodat de cue-color-tag nog door de regel loopt
        """
        dim = QBrush(QColor(TEXT_DIM))
        text = QBrush(QColor("#ffffff"))
        # Subtiele lichte overlay, géén volledig oranje meer — anders
        # botst 't met oranje-cues. We zetten 'm op alle kolommen zodat
        # de regel "oplicht" maar de cue-color nog leesbaar blijft.
        ph_bg_color = QColor(255, 255, 255, 60)  # 23% witte wash
        ph_bg = QBrush(ph_bg_color)

        playhead_id: str | None = None
        if 0 <= self._playhead_index < len(self.workspace.cues):
            playhead_id = self.workspace.cues[self._playhead_index].id

        for cue_id, item in self._id_to_item.items():
            cue = self.workspace.find(cue_id)
            is_ph = (cue_id == playhead_id)

            f = item.font(0)
            f.setBold(is_ph)
            for col in range(self.columnCount()):
                item.setFont(col, f)

            # Eerst de nummer-tekst normaliseren; in het ph-pad voegen we
            # daarna de ▶-marker toe. Anders blijft 'ie hangen op een
            # rij die vroeger ph was.
            if cue is not None:
                bare_num = cue.cue_number or str(
                    self.workspace.index_of(cue_id) + 1
                )
                item.setText(0, f"▶ {bare_num}" if is_ph else bare_num)

            if is_ph:
                # Lichte witte wash over de cue-color-tint heen — werkt op
                # zowel donkere als oranje rijen omdat 't compositioneel
                # mengt i.p.v. te overschrijven.
                if cue is not None and cue.color:
                    full = QBrush(QColor(cue.color))
                    item.setBackground(0, full)
                    for col in range(1, self.columnCount()):
                        # Mix tint met de witte wash voor 't playhead-effect.
                        tint = QColor(tint_for_row(cue.color))
                        tint.setAlpha(220)
                        item.setBackground(col, QBrush(tint))
                else:
                    for col in range(self.columnCount()):
                        item.setBackground(col, ph_bg)
                # Witte vette tekst voor maximaal contrast.
                for col in range(self.columnCount()):
                    item.setForeground(col, text)
                state_color = STATE_COLORS.get(
                    cue.state if cue else "idle", QColor("#ffffff")
                )
                item.setForeground(5, QBrush(state_color))
            else:
                # Reset naar cue-color-tag (zelfde logica als _make_item).
                if cue is not None and cue.color:
                    full = QBrush(QColor(cue.color))
                    tint = QBrush(tint_for_row(cue.color))
                    item.setBackground(0, full)
                    for col in range(1, self.columnCount()):
                        item.setBackground(col, tint)
                else:
                    empty = QBrush()
                    for col in range(self.columnCount()):
                        item.setBackground(col, empty)
                # Default-foregrounds — kolom 1 dim, status z'n eigen
                # state-color, rest QBrush() (= palette default).
                default_fg = QBrush()
                for col in range(self.columnCount()):
                    item.setForeground(col, default_fg)
                item.setForeground(1, dim)
                state_color = STATE_COLORS.get(
                    cue.state if cue else "idle", QColor("#888")
                )
                item.setForeground(5, QBrush(state_color))

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

    # ---- context menu (move into / out of group) -------------------------

    def _show_context_menu(self, pos) -> None:
        """Right-click → bouw een menu op basis van de huidige selectie.
        Toont alleen acties die zinnig zijn (move-into-group alleen als
        er een group bestaat die niet zelf in de selectie zit; move-out
        alleen als minstens één geselecteerde cue in een group zit)."""
        sel = self.selected_cues()
        if not sel:
            return
        menu = QMenu(self)

        # Vind alle Group-cues die niet zichzelf en geen ancestor van de
        # selectie zijn (anders maken we een cycle).
        sel_ids = {c.id for c in sel}
        candidate_groups: list[Cue] = []
        for c in self.workspace.cues:
            if c.cue_type != CueType.GROUP:
                continue
            if c.id in sel_ids:
                continue
            # Skip als deze group binnen de selectie zit (selectie verplaatst
            # naar zichzelf zou een loop veroorzaken).
            if any(self.workspace.is_in_group(c.id, sid) for sid in sel_ids):
                continue
            candidate_groups.append(c)

        if candidate_groups:
            sub = menu.addMenu("Move into group")
            for grp in candidate_groups:
                label = f"{grp.cue_number or '?'}: {grp.name or '(untitled)'}"
                act = QAction(label, sub)
                act.triggered.connect(
                    lambda _checked=False, gid=grp.id: self._move_into(gid)
                )
                sub.addAction(act)

        if any(c.parent_group_id for c in sel):
            act_out = QAction("Move out of group", menu)
            act_out.triggered.connect(lambda: self._move_into(""))
            menu.addAction(act_out)

        if not menu.actions():
            return  # niets nuttigs te tonen
        menu.exec(self.viewport().mapToGlobal(pos))

    def _move_into(self, new_parent_id: str) -> None:
        sink = getattr(self, "command_sink", None)
        if sink is None:
            return
        ids = [c.id for c in self.selected_cues()]
        sink.push_reparent_cues(ids, new_parent_id)

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
