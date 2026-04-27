"""Hoofdvenster — integreert cue-list, inspector, transport, menu's en
shortcuts met de PlaybackController."""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, QByteArray
from PyQt6.QtGui import (
    QAction, QKeySequence, QShortcut, QGuiApplication, QUndoStack,
)
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QFileDialog,
    QMessageBox, QStatusBar, QLabel, QScrollArea, QSizePolicy,
)

from .. import APP_NAME, APP_VERSION, WORKSPACE_EXT
from ..cues import Cue, CueType, ContinueMode
from ..i18n import t
from ..workspace import Workspace
from ..playback import PlaybackController
from ..engines import registry
from ..engines.audio import (
    register_status as register_audio_status,
    find_device_index_by_name,
)
from ..engines.image import register_status as register_image_status
from ..engines.osc import register_status as register_osc_status
from ..engines.osc_feedback import (
    OscFeedbackEngine,
    register_status as register_osc_feedback_status,
)
from ..engines.osc_out import register_status as register_osc_out_status
from ..engines.powerpoint import register_status as register_powerpoint_status
from ..engines.video import register_status as register_video_status

from .cuelist import CueListWidget
from .cuetoolbar import CueToolbar
from .inspector import InspectorWidget
from .transport import TransportWidget
from .dialogs import (
    show_about, EngineStatusDialog, LicenseDialog, PreferencesDialog,
    PptImportDialog, MODE_SLIDES, MODE_SINGLE,
)
from .dialogs.preferences import DEFAULT_SAMPLE_RATE, DEFAULT_OSC_PORT
from ..engines.powerpoint import (
    count_slides as ppt_count_slides,
    export_slides_to_png as ppt_export_slides,
    extract_slide_media as ppt_extract_slide_media,
    is_com_available as ppt_com_available,
)
from .. import licensing as licensing_mod
from ..undo import (
    RefreshHook, AddCueCmd, RemoveCuesCmd, MoveCueCmd, RenumberCmd, SetCueFieldCmd,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1400, 860)

        # Licensing — laad de actieve licentie van disk en cache 'm in
        # de licensing-module zodat has_feature() overal werkt zonder
        # disk-I/O. De UI mag deze state ook lezen voor een titlebar-
        # badge of statusbar-indicator.
        licensing_mod.init()

        # Model
        self.ws = Workspace()

        # Undo/redo — alle workspace-mutaties lopen via QUndoStack zodat
        # Edit → Undo / Redo (Ctrl+Z / Ctrl+Y) iedere actie netjes
        # terugdraait. De RefreshHook geeft de commands een handle om de
        # UI bij te werken zonder QWidget-dependencies in het undo-model.
        self.undo_stack = QUndoStack(self)
        self._undo_hook = RefreshHook(
            on_struct=self._on_undo_struct_changed,
            on_field=self._on_undo_field_changed,
        )

        # Audio-engine configureren vanuit QSettings (device + samplerate)
        # vóórdat de controller hem start.
        audio = self._build_audio_engine_from_settings()

        # Playback
        self.controller = PlaybackController(self.ws, parent=self, audio=audio)
        self.controller.cue_state_changed.connect(self._on_cue_state_changed)
        self.controller.running_changed.connect(self._on_running_changed)
        self.controller.network_send_failed.connect(self._on_network_send_failed)
        self.controller.cue_blocked_by_license.connect(self._on_cue_blocked_by_license)

        # OSC-input opstarten vanuit QSettings
        self._start_osc_from_settings()

        # Companion / OSC-feedback engine. Wordt nu gemaakt zodat
        # Preferences-dialog 'm kan binden; start is afhankelijk van
        # QSettings → _start_companion_feedback_from_settings.
        self.feedback = OscFeedbackEngine(self)
        self.feedback.set_provider(self)
        # Wanneer een cue van state wisselt, push direct (=geen wacht
        # tot volgende periodieke tick). Companion's feedback voelt dan
        # snappy.
        self.controller.cue_state_changed.connect(self._on_state_change_for_feedback)
        # NB. controller.playhead_changed → cue_list.set_playhead wordt
        # ná _build_ui() aangesloten, want de cue_list bestaat hier nog
        # niet.

        # Engine status registreren
        register_audio_status(self.controller.audio)
        register_osc_status(self.controller.osc)
        register_osc_out_status(self.controller.osc_out)
        register_video_status(self.controller.video)
        register_image_status(self.controller.image)
        register_powerpoint_status(self.controller.powerpoint)
        # Companion-feedback registreren — start gebeurt hieronder.
        register_osc_feedback_status(self.feedback)
        # VLC-audio-device uit QSettings toepassen
        self._apply_video_audio_device_from_settings()
        # Companion / Stream Deck feedback opstarten
        self._start_companion_feedback_from_settings()

        # UI
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._sync_title()

        # Inspector krijgt een handle naar de OSC-engine voor de Learn-dialog
        self.inspector.osc_engine = self.controller.osc
        # En naar de OSC-output engine voor de "Test verzenden"-knop op
        # Network-cues.
        self.inspector.osc_out_engine = self.controller.osc_out

        # Cuelist + inspector wijzen naar mainwindow zodat ze hun
        # mutaties via push_set_field / push_move_cue / etc. routen
        # ipv direct op de Workspace muteren. Routing via de undo-stack
        # is wat undo/redo überhaupt mogelijk maakt.
        self.cue_list.command_sink = self
        self.inspector.command_sink = self

        # Playhead via OSC verplaatst → cuelist mee laten lopen. Bij
        # GO-via-OSC advancet de controller z'n eigen index in go();
        # de cuelist syncen we hier alsnog zodat 't visueel klopt. Pas
        # nu aansluitbaar omdat cue_list door _build_ui() is gemaakt.
        self.controller.playhead_changed.connect(self.cue_list.set_playhead)

        # Vensterpositie + -grootte herstellen (na _build_ui zodat de child-
        # widgets bestaan en de splitter z'n geometrie krijgt).
        self._restore_window_geometry()

    # ---- build ------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        vroot = QVBoxLayout(central)
        vroot.setContentsMargins(0, 0, 0, 0)
        vroot.setSpacing(0)

        self.transport = TransportWidget(
            countdown_source=self.controller.primary_countdown
        )
        self.transport.go_clicked.connect(self.action_go)
        self.transport.stop_all_clicked.connect(self.action_stop_all)
        vroot.addWidget(self.transport)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        vroot.addWidget(splitter, 1)

        # Linkerkant: cue-toolbar boven de cuelist
        left_side = QWidget()
        left_layout = QVBoxLayout(left_side)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.cue_toolbar = CueToolbar()
        self.cue_toolbar.new_cue.connect(self.action_new_cue)
        self.cue_toolbar.delete_selected.connect(self.action_delete_selected)
        self.cue_toolbar.renumber.connect(self.action_renumber)
        self.cue_toolbar.move_up.connect(lambda: self.cue_list.move_selected(-1))
        self.cue_toolbar.move_down.connect(lambda: self.cue_list.move_selected(1))
        # Wikkel de toolbar in een horizontale scroll-area zodat 'ie geen
        # minimum-breedte oplegt aan de splitter — anders blokkeert de
        # som van de 13 knoppen het slepen van de splitter ("hortend").
        toolbar_scroll = QScrollArea()
        toolbar_scroll.setWidget(self.cue_toolbar)
        toolbar_scroll.setWidgetResizable(True)
        toolbar_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        toolbar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        toolbar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        toolbar_scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        toolbar_scroll.setFixedHeight(self.cue_toolbar.sizeHint().height())
        left_layout.addWidget(toolbar_scroll)

        self.cue_list = CueListWidget(self.ws)
        self.cue_list.cue_selected.connect(self._on_cue_selected)
        self.cue_list.playhead_changed.connect(self._on_playhead_changed)
        self.cue_list.go_requested.connect(self.action_go)
        self.cue_list.files_dropped.connect(self._on_files_dropped)
        self.cue_list.cue_field_edited.connect(self._on_cue_field_edited)
        left_layout.addWidget(self.cue_list, 1)

        splitter.addWidget(left_side)

        self.inspector = InspectorWidget(self.ws)
        self.inspector.cue_changed.connect(self._on_inspector_changed)
        splitter.addWidget(self.inspector)

        # Inspector zit rechts en blijft op z'n vaste breedte staan; de
        # cue-list links absorbeert alle resize-ruimte.
        # setCollapsible(1, False) blokkeert per ongeluk wegslepen.
        # Minimum bewust laag (220) zodat slepen aan de splitter-grip
        # vloeiend gaat — anders snapt 'ie terug bij elke resize-stap.
        self._splitter = splitter
        self._inspector_width = 420
        self.inspector.setMinimumWidth(220)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(1, False)
        # Voorkom dat het venster zo smal wordt dat de inspector uit
        # beeld geduwd wordt aan de rechterkant.
        self.setMinimumWidth(self.inspector.minimumWidth() + 320)

        # Statusbar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel("")
        sb.addPermanentWidget(self.status_label)
        self._refresh_statusbar()

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # File
        m_file = mb.addMenu("&File")
        m_file.setToolTipsVisible(True)
        self._add_action(m_file, "New", self.action_new, QKeySequence.StandardKey.New,
                         tip="Create a new, empty workspace (closes the current one)")
        self._add_action(m_file, "Open…", self.action_open, QKeySequence.StandardKey.Open,
                         tip="Open an existing .livefire workspace from disk")
        self._add_action(m_file, "Save", self.action_save, QKeySequence.StandardKey.Save,
                         tip="Write the current workspace (Save As… on first use)")
        self._add_action(m_file, "Save As…", self.action_save_as, QKeySequence.StandardKey.SaveAs,
                         tip="Save the workspace to a new .livefire file")
        m_file.addSeparator()
        self._add_action(m_file, "Preferences…", self.action_preferences, QKeySequence("Ctrl+,"),
                         tip="Configure audio device, sample rate, and OSC input")
        m_file.addSeparator()
        self._add_action(m_file, "Exit", self.close, QKeySequence("Ctrl+Q"),
                         tip="Close liveFire")

        # Edit
        m_edit = mb.addMenu("&Edit")
        m_edit.setToolTipsVisible(True)
        # Standaard Qt-undo/redo-actions volgen de stack-state automatisch:
        # ze worden disabled wanneer er niets te undo'n/redo'n is, en hun
        # label leest "Undo Add cue" / "Undo Set volume" etc.
        self.act_undo = self.undo_stack.createUndoAction(self, "Undo")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        m_edit.addAction(self.act_undo)
        self.act_redo = self.undo_stack.createRedoAction(self, "Redo")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        self._add_action(m_edit, "Cut", self.action_cut, QKeySequence.StandardKey.Cut,
                         tip="Cut the selected cue(s) to the clipboard")
        self._add_action(m_edit, "Copy", self.action_copy, QKeySequence.StandardKey.Copy,
                         tip="Copy the selected cue(s) to the clipboard")
        self._add_action(m_edit, "Paste", self.action_paste, QKeySequence.StandardKey.Paste,
                         tip="Paste cue(s) from the clipboard after the playhead")

        # Cue
        m_cue = mb.addMenu("&Cue")
        m_cue.setToolTipsVisible(True)
        self._add_action(m_cue, "New Audio Cue", lambda: self.action_new_cue(CueType.AUDIO), QKeySequence("Ctrl+1"),
                         tip="Play an audio file with volume, loops, and fades")
        self._add_action(m_cue, "New Video Cue", lambda: self.action_new_cue(CueType.VIDEO), QKeySequence("Ctrl+2"),
                         tip="Play a video file fullscreen on the selected screen (libVLC)")
        self._add_action(m_cue, "New Image Cue", lambda: self.action_new_cue(CueType.IMAGE), QKeySequence("Ctrl+3"),
                         tip="Display a still image fullscreen on the selected screen (Qt)")
        self._add_action(m_cue, "New Presentation Cue", lambda: self.action_new_cue(CueType.PRESENTATION), QKeySequence("Ctrl+4"),
                         tip="Control a PowerPoint presentation via COM (Open / Next Slide / Previous / Go To / Close)")
        self._add_action(m_cue, "New Network Cue", lambda: self.action_new_cue(CueType.NETWORK), QKeySequence("Ctrl+5"),
                         tip="Send an OSC message to an external receiver (Companion, QLab, SQ5, …)")
        self._add_action(m_cue, "New Fade Cue", lambda: self.action_new_cue(CueType.FADE), QKeySequence("Ctrl+6"),
                         tip="Change the volume of another (running) audio cue over time")
        self._add_action(m_cue, "New Wait Cue", lambda: self.action_new_cue(CueType.WAIT), QKeySequence("Ctrl+7"),
                         tip="Pause for a fixed duration in the playback sequence")
        self._add_action(m_cue, "New Stop Cue", lambda: self.action_new_cue(CueType.STOP), QKeySequence("Ctrl+8"),
                         tip="Stop a specific cue or (empty target) everything")
        self._add_action(m_cue, "New Group Cue", lambda: self.action_new_cue(CueType.GROUP), QKeySequence("Ctrl+9"),
                         tip="Container for multiple cues (placeholder in v0.3)")
        self._add_action(m_cue, "New Memo Cue", lambda: self.action_new_cue(CueType.MEMO), QKeySequence("Ctrl+0"),
                         tip="Note only — does nothing on GO")
        self._add_action(m_cue, "New Start Cue", lambda: self.action_new_cue(CueType.START),
                         tip="Trigger another cue on GO (useful for re-use)")
        m_cue.addSeparator()
        self._add_action(m_cue, "Delete", self.action_delete_selected, QKeySequence.StandardKey.Delete,
                         tip="Delete the selected cue(s)")
        self._add_action(m_cue, "Renumber", self.action_renumber,
                         tip="Renumber all cues sequentially starting from 1")

        # Transport
        m_tr = mb.addMenu("&Transport")
        m_tr.setToolTipsVisible(True)
        self._add_action(m_tr, "GO", self.action_go, QKeySequence("Space"),
                         tip="Start the cue at the playhead and advance the playhead")
        self._add_action(m_tr, "Stop All", self.action_stop_all, QKeySequence("Escape"),
                         tip="Stop all active cues immediately (panic)")

        # Help
        m_help = mb.addMenu("&Help")
        m_help.setToolTipsVisible(True)
        self._add_action(m_help, "Engine Status…", self.action_engine_status,
                         tip="Show which engines (Audio, OSC) are available and their status")
        if licensing_mod.LICENSING_ENABLED:
            self._add_action(m_help, "License…", self.action_license,
                             tip="Show the active license and allow importing a new one")
        self._add_action(m_help, f"About {APP_NAME}…", self.action_about,
                         tip=f"About {APP_NAME} — version and author")

    def _build_shortcuts(self) -> None:
        # Zet de QAction-shortcuts uit het menu op application-wide context zodat
        # ze werken ongeacht widget-focus. Eerder stonden hier duplicate
        # QShortcut-objecten die conflicteerden met dezelfde keys in het menu
        # ("QAction::event: Ambiguous shortcut overload: Space").
        for action in self.menuBar().findChildren(QAction):
            if action.shortcut().toString():
                action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

    @staticmethod
    def _add_action(menu, text, slot, shortcut=None, tip: str = "") -> QAction:
        a = QAction(text, menu)
        if shortcut is not None:
            a.setShortcut(shortcut)
        if tip:
            a.setToolTip(tip)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    # ---- actions: file ----------------------------------------------------

    def action_new(self) -> None:
        if not self._confirm_discard():
            return
        self.ws = Workspace()
        self.controller.set_workspace(self.ws)
        self.cue_list.workspace = self.ws
        self.inspector.workspace = self.ws
        self.cue_list.refresh()
        self.inspector.set_cue(None)
        self.cue_list.set_playhead(0)
        self._sync_title()

    def action_open(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Workspace", "",
            f"liveFire workspace (*{WORKSPACE_EXT});;All files (*)",
        )
        if not path:
            return
        try:
            ws = Workspace.load(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Cannot Open", str(e))
            return
        self.ws = ws
        self.controller.set_workspace(self.ws)
        self.cue_list.workspace = self.ws
        self.inspector.workspace = self.ws
        self.cue_list.refresh()
        self.inspector.set_cue(None)
        self.cue_list.set_playhead(0)
        self._sync_title()

    def action_save(self) -> None:
        if self.ws.path is None:
            self.action_save_as()
            return
        try:
            self.ws.save()
        except Exception as e:
            QMessageBox.critical(self, "Cannot Save", str(e))
            return
        self._sync_title()

    def action_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Workspace As", "",
            f"liveFire workspace (*{WORKSPACE_EXT})",
        )
        if not path:
            return
        if not path.endswith(WORKSPACE_EXT):
            path += WORKSPACE_EXT
        try:
            self.ws.save(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Cannot Save", str(e))
            return
        self._sync_title()

    # ---- actions: cue -----------------------------------------------------

    def action_new_cue(self, cue_type: str) -> None:
        n = len(self.ws.cues) + 1
        cue = Cue(cue_type=cue_type, cue_number=str(n), name=f"{cue_type} {n}")
        # Invoegen achter huidige selectie
        sel = self.cue_list.selected_cues()
        idx = self.ws.index_of(sel[-1].id) + 1 if sel else None
        self.push_add_cue(cue, index=idx, label=f"Add {cue_type} cue")
        self.cue_list.select_cue(cue.id)

    def action_delete_selected(self) -> None:
        cues = self.cue_list.selected_cues()
        if not cues:
            return
        # Stop eventueel lopende cues vóór de delete — dat is een runtime-
        # actie, geen state-mutatie, dus blijft buiten de undo-stack.
        for c in cues:
            self.controller.stop_cue(c.id)
        self.push_remove_cues(cues)
        self.inspector.set_cue(None)

    def action_renumber(self) -> None:
        self.push_renumber()

    # ---- actions: transport -----------------------------------------------

    def action_go(self) -> None:
        if self.controller.playhead_index >= len(self.ws.cues):
            return
        self.controller.go()
        new_idx = self.controller.playhead_index
        self.cue_list.set_playhead(new_idx)
        # Selectie en focus volgen de playhead zodat pijltjestoetsen en Spatie
        # blijven werken zonder dat de gebruiker eerst een cue moet aanklikken.
        if 0 <= new_idx < len(self.ws.cues):
            self.cue_list.select_cue(self.ws.cues[new_idx].id)
        self.cue_list.setFocus()

    def action_stop_all(self) -> None:
        self.controller.stop_all()
        self.cue_list.setFocus()

    # ---- actions: help ----------------------------------------------------

    def action_engine_status(self) -> None:
        dlg = EngineStatusDialog(self)
        dlg.exec()

    def action_license(self) -> None:
        dlg = LicenseDialog(self)
        dlg.exec()
        # De gebruiker kan in de dialog een licentie hebben geïmporteerd
        # of verwijderd — refresh de titel zodat een eventuele Pro/FREE-
        # badge meteen klopt.
        self._sync_title()

    def action_preferences(self) -> None:
        dlg = PreferencesDialog(
            self.controller.audio, self.controller.osc,
            self.controller.video, feedback=self.feedback, parent=self,
        )
        if dlg.exec():
            self._refresh_statusbar()

    def action_about(self) -> None:
        show_about(self)

    # ---- audio-engine config ----------------------------------------------

    def _build_audio_engine_from_settings(self):
        from ..engines import AudioEngine
        s = QSettings()
        device_name = s.value("audio/device_name", "", type=str)
        sr = s.value("audio/samplerate", DEFAULT_SAMPLE_RATE, type=int)
        device = find_device_index_by_name(device_name) if device_name else None
        return AudioEngine(sample_rate=sr, device=device)

    def _apply_video_audio_device_from_settings(self) -> None:
        s = QSettings()
        dev = s.value("video/audio_device", "", type=str)
        if dev:
            self.controller.video.set_audio_device(dev)

    def _start_osc_from_settings(self) -> None:
        s = QSettings()
        if not s.value("osc/enabled", False, type=bool):
            return
        port = s.value("osc/port", DEFAULT_OSC_PORT, type=int)
        ok, err = self.controller.osc.start(int(port))
        if not ok:
            QMessageBox.warning(
                self, "OSC input not started",
                f"Could not start OSC on port {port}: {err}",
            )

    def _start_companion_feedback_from_settings(self) -> None:
        s = QSettings()
        if not s.value("companion/enabled", False, type=bool):
            return
        host = s.value("companion/host", "127.0.0.1", type=str)
        port = s.value("companion/port", 12321, type=int)
        interval = s.value("companion/interval_ms", 100, type=int)
        ok, err = self.feedback.start(host, int(port), int(interval))
        register_osc_feedback_status(self.feedback)
        if not ok:
            QMessageBox.warning(
                self, "Companion feedback not started",
                f"Could not connect to {host}:{port}: {err}",
            )
            return
        # Initiële snapshot van de hele cuelist zodat Companion meteen
        # weet welke cues bestaan (anders pas zichtbaar bij de eerste
        # state-change op een cue).
        self._broadcast_cuelist_snapshot()

    # ---- snapshot-provider voor OscFeedbackEngine ------------------------

    def snapshot(self) -> dict:
        """Wordt door OscFeedbackEngine elke tick aangeroepen om een
        platte dict van transport-state op te halen — zonder dat de
        engine iets weet van Workspace of controller-internals."""
        cd = self.controller.primary_countdown()
        if cd is None:
            remaining = 0.0
            remaining_label = ""
            countdown_active = False
        else:
            label, seconds, is_countdown = cd
            remaining = seconds if is_countdown else -seconds
            remaining_label = label
            countdown_active = is_countdown
        playhead = self.controller.playhead_index
        total = len(self.ws.cues)
        if 0 <= playhead < total:
            phn = self.ws.cues[playhead].name or self.ws.cues[playhead].cue_number
        else:
            phn = ""
        return {
            "playhead": playhead,
            "playhead_total": total,
            "playhead_name": phn,
            "active": len(self.controller.audio.active_cue_ids()),
            "remaining": remaining,
            "remaining_label": remaining_label,
            "countdown_active": countdown_active,
        }

    def _on_state_change_for_feedback(self, cue_id: str) -> None:
        """Push een per-cue state-update zodra een cue van fase wisselt
        (idle ↔ running ↔ finished)."""
        if not self.feedback.running:
            return
        cue = self.ws.find(cue_id)
        if cue is None:
            return
        self.feedback.send_cue_state(cue.cue_number, cue.state)

    def _broadcast_cuelist_snapshot(self) -> None:
        """Push naam + type + state voor iedere cue. Zware push, dus
        alleen bij workspace-mutaties (open / new / paste / drop) en
        bij eerste connect."""
        if not self.feedback.running:
            return
        self.feedback.send_cuecount(len(self.ws.cues))
        for cue in self.ws.cues:
            self.feedback.send_cue_meta(cue.cue_number, cue.name, cue.cue_type)
            self.feedback.send_cue_state(cue.cue_number, cue.state)

    # ---- reactive handlers ------------------------------------------------

    def _on_cue_selected(self, _cue: Cue | None) -> None:
        # We negeren de enkelvoudige parameter en halen de hele selectie
        # op, zodat de inspector multi-select kan tonen.
        self.inspector.set_cues(self.cue_list.selected_cues())

    def _on_inspector_changed(self, cue: Cue) -> None:
        # Targeted update per cue zodat keyboard-focus op inspector-spinboxen
        # niet naar de cuelist verspringt bij elke value-change. Bij multi-
        # select doen we 'm voor alle geselecteerde cues.
        for c in self.inspector.cues or [cue]:
            self.cue_list.update_cue_display(c.id)
        self._sync_title()

    def _on_cue_state_changed(self, cue_id: str) -> None:
        self.cue_list.update_cue(cue_id)

    def _on_cue_field_edited(self, cue_id: str) -> None:
        """Inline edit in de cue-list (bv. Continue-kolom-dropdown) — sync
        de inspector als deze cue daar actief is, en zet de title-asterisk
        zodat de operator ziet dat de workspace dirty is."""
        if (self.inspector.cue is not None
                and self.inspector.cue.id == cue_id):
            self.inspector.set_cue(self.inspector.cue)
        self._sync_title()

    # ---- undo/redo refresh hooks -----------------------------------------

    def _on_undo_struct_changed(self) -> None:
        """Wordt aangeroepen door commands die de cuelist-structuur muteren
        (add/remove/move/renumber). Volledige refresh van de cuelist en
        revalidatie van de inspector-keuze."""
        self.cue_list.refresh()
        cur = self.inspector.cue
        if cur is not None and self.ws.find(cur.id) is None:
            # Geselecteerde cue is door undo/redo verdwenen.
            self.inspector.set_cue(None)
        self._sync_title()
        # Push een nieuwe cue-snapshot naar Companion zodat z'n preset-
        # labels meebewegen met de nieuwe structuur.
        self._broadcast_cuelist_snapshot()

    def _on_undo_field_changed(self, _cue_id: str) -> None:
        """Veld op één cue is gemuteerd via undo-stack. UI-refresh + push
        bijgewerkte naam/type naar Companion (bv. naam-edit moet ook in
        Stream Deck-label terug te zien zijn). Bewust hier centraal in
        plaats van in iedere setter — alle field-edits gaan via de
        undo-stack, dus dit pad pakt ze allemaal."""
        # De veldspecifieke UI-update doet de bestaande hook al; we
        # voegen alleen de Companion-push toe. We sturen meta + state
        # ongeacht welk veld is veranderd; het is goedkoop.
        cue = self.ws.find(_cue_id)
        if cue is not None and self.feedback.running:
            self.feedback.send_cue_meta(cue.cue_number, cue.name, cue.cue_type)
            self.feedback.send_cue_state(cue.cue_number, cue.state)
        self._cue_field_refresh(_cue_id)

    def _cue_field_refresh(self, cue_id: str) -> None:
        """Bestaande field-refresh-logica, los gezet zodat
        ``_on_undo_field_changed`` 'm kan blijven aanroepen na de
        Companion-push."""
        self.cue_list.update_cue_display(cue_id)
        if (self.inspector.cue is not None
                and self.inspector.cue.id == cue_id):
            self.inspector.set_cue(self.inspector.cue)
        self._sync_title()

    # ---- command-sink API (cuelist + inspector + drag-drop loops) --------

    def push_add_cue(self, cue: Cue, index: int | None = None,
                     label: str = "Add cue") -> None:
        self.undo_stack.push(
            AddCueCmd(self.ws, cue, index, self._undo_hook, label)
        )

    def push_remove_cues(self, cues: list[Cue]) -> None:
        if not cues:
            return
        self.undo_stack.push(RemoveCuesCmd(self.ws, cues, self._undo_hook))

    def push_move_cue(self, cue_id: str, delta: int) -> None:
        self.undo_stack.push(MoveCueCmd(self.ws, cue_id, delta, self._undo_hook))

    def push_renumber(self) -> None:
        self.undo_stack.push(RenumberCmd(self.ws, self._undo_hook))

    def push_set_field(self, cue_ids: list[str], field: str, new_value) -> None:
        self.undo_stack.push(
            SetCueFieldCmd(self.ws, cue_ids, field, new_value, self._undo_hook)
        )

    def begin_macro(self, label: str) -> None:
        """Wrap meerdere commands tot één undo-entry — gebruikt voor
        bulk-imports (drag-drop, PPT-slides) en cut-en-paste."""
        self.undo_stack.beginMacro(label)

    def end_macro(self) -> None:
        self.undo_stack.endMacro()

    # ---- clipboard (cut / copy / paste) ----------------------------------

    def action_copy(self) -> None:
        cues = self.cue_list.selected_cues()
        if cues:
            self._copy_cues_to_clipboard(cues)

    def action_cut(self) -> None:
        cues = self.cue_list.selected_cues()
        if not cues:
            return
        self._copy_cues_to_clipboard(cues)
        self.begin_macro(f"Cut {len(cues)} cue(s)" if len(cues) != 1 else "Cut cue")
        for c in cues:
            self.controller.stop_cue(c.id)
        self.push_remove_cues(cues)
        self.end_macro()

    def action_paste(self) -> None:
        cues = self._read_cues_from_clipboard()
        if not cues:
            return
        # Insert na de huidige selectie (of het einde als er niks geselecteerd is)
        sel = self.cue_list.selected_cues()
        if sel:
            insert_at = self.ws.index_of(sel[-1].id) + 1
        else:
            insert_at = self.controller.playhead_index
        self.begin_macro(
            f"Paste {len(cues)} cue(s)" if len(cues) != 1 else "Paste cue"
        )
        for offset, c in enumerate(cues):
            self.push_add_cue(c, index=insert_at + offset, label="Paste cue")
        self.end_macro()
        # Selecteer de geplakte cues zodat de operator meteen verder kan
        if cues:
            self.cue_list.select_cue(cues[0].id)

    def _copy_cues_to_clipboard(self, cues: list[Cue]) -> None:
        """Serialiseer naar JSON met een eigen MIME-type zodat we 'm bij
        paste herkennen, plus een platte text-fallback voor zicht-debug
        in andere apps."""
        import json
        from PyQt6.QtCore import QMimeData
        from PyQt6.QtWidgets import QApplication
        payload = {
            "format": "livefire/cues-v1",
            "cues": [c.to_dict() for c in cues],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        mime = QMimeData()
        mime.setData("application/x-livefire-cues", text.encode("utf-8"))
        mime.setText(text)
        QApplication.clipboard().setMimeData(mime)

    def _read_cues_from_clipboard(self) -> list[Cue]:
        """Decode wat we eerder met _copy_cues_to_clipboard hebben gezet.
        Genereert nieuwe UUIDs zodat geplakte cues hun eigen identity
        hebben (anders zou een Stop-cue per ongeluk de oorspronkelijke
        cue targeten i.p.v. de paste-kopie)."""
        import json, uuid
        from PyQt6.QtWidgets import QApplication
        mime = QApplication.clipboard().mimeData()
        raw = ""
        if mime.hasFormat("application/x-livefire-cues"):
            raw = bytes(mime.data("application/x-livefire-cues")).decode("utf-8", "ignore")
        elif mime.hasText():
            raw = mime.text()
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(payload, dict) or payload.get("format") != "livefire/cues-v1":
            return []
        out: list[Cue] = []
        for cd in payload.get("cues", []):
            try:
                cue = Cue.from_dict(cd)
            except Exception:
                continue
            cue.id = str(uuid.uuid4())  # unique identity per paste
            cue.state = "idle"
            out.append(cue)
        return out

    def _on_network_send_failed(self, cue_id: str, err: str) -> None:
        """Toon een transiënte waarschuwing in de statusbar als een
        Network-cue's OSC-send mislukte. Anders zou de operator pas
        merken dat de trigger niet aankwam doordat de receiver niet
        reageert."""
        cue = self.ws.find(cue_id)
        name = cue.name if cue else cue_id[:8]
        msg = f"⚠ Network cue '{name}' failed: {err}"
        # showMessage met timeout 4000ms — verschijnt links in de statusbar.
        self.statusBar().showMessage(msg, 4000)

    def _on_cue_blocked_by_license(self, cue_id: str, cue_type: str) -> None:
        """Een cue is geskipt omdat het cue-type een Pro-licentie vereist.
        Flash een melding in de statusbar — niet een modal, want de show
        moet kunnen doorlopen."""
        cue = self.ws.find(cue_id)
        name = cue.name if cue else cue_id[:8]
        msg = (
            f"🔒 '{name}' ({cue_type}) requires a Pro license — "
            f"open Help → License…"
        )
        self.statusBar().showMessage(msg, 6000)

    def _on_running_changed(self) -> None:
        self.transport.set_active_count(len(self.controller.audio.active_cue_ids()))

    # Bestandstype-herkenning voor drag-and-drop. Video en afbeeldingen worden
    # nu als placeholder-Memo ingevoegd (echte cue-types komen in v0.6.0).
    _AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif", ".m4a"}
    _VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif"}
    _PPT_EXTS = {".pptx", ".ppt", ".pptm"}

    def _on_files_dropped(self, paths: list[str]) -> None:
        # Eerst alle PPTs uit de drop scheiden — voor PPTs vragen we per
        # bestand hoe ze toegevoegd moeten worden, en met een "toepassen
        # op alle"-checkbox als er meerdere zijn.
        ppt_paths: list[Path] = []
        other_paths: list[Path] = []
        for p in paths:
            path = Path(p)
            if path.suffix.lower() in self._PPT_EXTS:
                ppt_paths.append(path)
            else:
                other_paths.append(path)

        # Hele drop is één undo-entry — de operator kan dus 1× Ctrl+Z
        # doen om een ongelukkige drop ongedaan te maken, in plaats van
        # N× per geïmporteerde cue.
        self.begin_macro(
            f"Drop {len(other_paths) + len(ppt_paths)} file(s)"
        )
        try:
            # ---- niet-PPT-bestanden: ongewijzigd gedrag --------------------
            for path in other_paths:
                ext = path.suffix.lower()
                n = len(self.ws.cues) + 1
                if ext in self._AUDIO_EXTS:
                    cue = Cue(cue_type=CueType.AUDIO, cue_number=str(n),
                              name=path.stem, file_path=str(path))
                elif ext in self._VIDEO_EXTS:
                    cue = Cue(cue_type=CueType.VIDEO, cue_number=str(n),
                              name=path.stem, file_path=str(path))
                elif ext in self._IMAGE_EXTS:
                    # v0.4.1: image-drop maakt nu een echte Image-cue (was Memo
                    # placeholder). De Image-engine kan deze direct fullscreen
                    # tonen.
                    cue = Cue(cue_type=CueType.IMAGE, cue_number=str(n),
                              name=path.stem, file_path=str(path))
                else:
                    continue
                self.push_add_cue(cue, label=f"Add {cue.cue_type} cue")

            # ---- PPT-bestanden: per bestand een keuze vragen --------------
            forced_mode: str | None = None
            for path in ppt_paths:
                mode = forced_mode

                if mode is None:
                    # Probeer eerst zelf het aantal slides te tellen (alleen
                    # voor .pptx/.pptm — voor .ppt komt None terug).
                    detected = ppt_count_slides(str(path))
                    show_apply = (len(ppt_paths) > 1 and forced_mode is None)
                    dlg = PptImportDialog(
                        str(path), detected,
                        com_available=ppt_com_available(),
                        show_apply_to_all=show_apply, parent=self,
                    )
                    if dlg.exec() != dlg.DialogCode.Accepted:
                        continue
                    mode = dlg.chosen_mode()
                    if dlg.apply_to_all():
                        forced_mode = mode

                self._add_ppt_cues(path, mode)
        finally:
            self.end_macro()

    def _add_ppt_cues(self, path: Path, mode: str) -> int:
        """Voeg cues voor één PPT-bestand toe op basis van keuze. Geeft
        het aantal toegevoegde cues terug."""
        from ..cues import PresentationAction
        n = len(self.ws.cues) + 1

        if mode == MODE_SINGLE:
            cue = Cue(cue_type=CueType.PRESENTATION, cue_number=str(n),
                      name=path.stem, file_path=str(path),
                      presentation_action=PresentationAction.OPEN)
            self.push_add_cue(cue, label="Add Presentation cue")
            return 1

        # MODE_SLIDES — exporteer iedere slide naar PNG via PowerPoint COM
        # en maak per slide een Image-cue. Assets gaan in een folder naast
        # het PPT-bestand: ``<pptx_parent>/<pptx_stem>_slides/``. Op die
        # manier zijn de PNGs gekoppeld aan het bron-bestand en niet aan
        # een specifieke workspace.
        out_dir = path.parent / f"{path.stem}_slides"
        png_paths = self._export_pptx_to_pngs_with_progress(path, out_dir)
        if png_paths is None:
            return 0  # gebruiker annuleerde of export faalde

        # Embedded audio/video uitpakken (incl. timing-tree-interpretatie:
        # autoplay vs click, loop, delay, volume). Voor .ppt geeft dit een
        # lege dict terug; voor .pptx/.pptm krijgen we per slide de
        # bijbehorende SlideMedia-records.
        media_per_slide = ppt_extract_slide_media(str(path), str(out_dir))

        added = 0
        for i, png in enumerate(png_paths, start=1):
            image_cue = Cue(
                cue_type=CueType.IMAGE,
                cue_number=str(n + added),
                name=f"{path.stem} — slide {i}",
                file_path=png,
            )
            self.push_add_cue(image_cue, label="Add Image cue")
            added += 1

            # Direct na de Image-cue: één Audio-/Video-cue per embedded
            # mediabestand op deze slide. Volgorde volgt de rId-suffix
            # (= insertion-order in PowerPoint).
            #
            # Timing-tree → cue-velden:
            #   * trigger="auto" → vorige cue krijgt AUTO_CONTINUE (zodra
            #     de slide-image start, vuurt deze media direct mee). Bij
            #     "click" blijft de vorige cue MANUAL en wacht de operator.
            #   * delay_s → pre_wait
            #   * loop=True → loops=0 (oneindig)
            #   * volume (lineair) → volume_db (klemmen op −60..0 dB)
            prev_cue = image_cue
            for media in media_per_slide.get(i, []):
                ctype = CueType.AUDIO if media.kind == "audio" else CueType.VIDEO

                if media.trigger == "auto":
                    prev_cue.continue_mode = ContinueMode.AUTO_CONTINUE

                if media.volume <= 0.0:
                    vol_db = -60.0
                else:
                    vol_db = max(-60.0, min(0.0, 20.0 * math.log10(media.volume)))

                mcue = Cue(
                    cue_type=ctype,
                    cue_number=str(n + added),
                    name=f"{path.stem} — slide {i} — {Path(media.path).name}",
                    file_path=media.path,
                    pre_wait=media.delay_s,
                    loops=0 if media.loop else 1,
                    volume_db=vol_db,
                )
                self.push_add_cue(mcue, label=f"Add {ctype} cue")
                added += 1
                prev_cue = mcue
        return added

    def _export_pptx_to_pngs_with_progress(
        self, src: Path, out_dir: Path,
    ) -> list[str] | None:
        """Run de slide-export met een QProgressDialog. Returns lijst met
        PNG-paden bij succes, of None bij annuleren / fout."""
        from PyQt6.QtWidgets import QProgressDialog, QMessageBox

        prog = QProgressDialog(
            t("pptimport.exporting_label").format(i=0, n=0),
            t("btn.cancel"),
            0, 0, self,
        )
        prog.setWindowTitle(t("pptimport.exporting_title"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setAutoClose(False)
        prog.show()
        # Force eerste paint zodat de dialog ook bij snelle exports zichtbaar is.
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        def _cb(i: int, total: int) -> bool:
            if prog.maximum() != total:
                prog.setMaximum(total)
            prog.setValue(i)
            prog.setLabelText(t("pptimport.exporting_label").format(i=i, n=total))
            QApplication.processEvents()
            return prog.wasCanceled()

        ok, paths, err = ppt_export_slides(
            str(src), str(out_dir), progress_callback=_cb,
        )
        prog.close()

        if not ok:
            if err == "Geannuleerd":
                return None
            QMessageBox.warning(
                self, t("pptimport.export_failed"),
                f"{src.name}\n\n{err}",
            )
            return None
        return paths

    def _on_playhead_changed(self, index: int) -> None:
        self.controller.set_playhead(index)
        total = len(self.ws.cues)
        label = ""
        if index < total:
            c = self.ws.cues[index]
            label = f"{c.cue_type}: {c.name}"
        self.transport.set_playhead(index, total, label)

    # ---- misc -------------------------------------------------------------

    def _refresh_statusbar(self) -> None:
        failed = registry.failed_shortnames()
        if failed:
            self.status_label.setText("⚠ " + " · ".join(f"{n}: ✗" for n in failed))
        else:
            self.status_label.setText("All engines OK")

    def _sync_title(self) -> None:
        name = self.ws.path.name if self.ws.path else "Untitled"
        dirty = "*" if self.ws.dirty else ""
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — {name}{dirty}")

    def _confirm_discard(self) -> bool:
        if not self.ws.dirty:
            return True
        r = QMessageBox.question(
            self, "Unsaved Changes",
            "There are unsaved changes. Continue and discard changes?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return r == QMessageBox.StandardButton.Discard

    _splitter_sized = False

    def showEvent(self, e) -> None:  # type: ignore[override]
        super().showEvent(e)
        # Eénmalig: zet de splitter zodat de inspector op z'n vaste
        # breedte aan de rechterkant staat en de cue-list de rest
        # absorbeert. Pas na show() heeft de splitter z'n echte width;
        # in __init__ is die nog 0.
        if not self._splitter_sized and hasattr(self, "_splitter"):
            self._splitter_sized = True
            total = self._splitter.width()
            if total > self._inspector_width:
                self._splitter.setSizes(
                    [total - self._inspector_width, self._inspector_width]
                )

    def closeEvent(self, e) -> None:
        if not self._confirm_discard():
            e.ignore()
            return
        self._save_window_geometry()
        self.feedback.shutdown()
        self.controller.shutdown()
        super().closeEvent(e)

    # ---- window geometry persistence -------------------------------------

    _GEOMETRY_KEY = "ui/main_geometry"
    _STATE_KEY = "ui/main_state"

    def _save_window_geometry(self) -> None:
        s = QSettings()
        s.setValue(self._GEOMETRY_KEY, self.saveGeometry())
        s.setValue(self._STATE_KEY, self.saveState())

    def _restore_window_geometry(self) -> None:
        """Probeer de opgeslagen geometrie te herstellen. Alleen toepassen
        als het venster minstens deels op een actief scherm valt — anders
        blijft de default-resize/-positie staan zodat een eerdere
        multi-monitor-config het venster niet buiten beeld parkeert."""
        s = QSettings()
        geom = s.value(self._GEOMETRY_KEY, QByteArray())
        if isinstance(geom, QByteArray) and not geom.isEmpty():
            if self.restoreGeometry(geom) and self._geometry_on_visible_screen():
                state = s.value(self._STATE_KEY, QByteArray())
                if isinstance(state, QByteArray) and not state.isEmpty():
                    self.restoreState(state)
                return
        # Geen bruikbare opgeslagen geometrie → centreer op het scherm waar
        # de cursor staat (of het primary-scherm als fallback).
        self._center_on_active_screen()

    def _geometry_on_visible_screen(self) -> bool:
        """True als het venster-rect overlap heeft met een actief scherm.
        Voorkomt dat een verdwenen extern scherm het venster onbereikbaar
        achterlaat."""
        win_rect = self.frameGeometry()
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(win_rect):
                return True
        return False

    def _center_on_active_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        # Klem grootte op wat past, centreer dan in availableGeometry.
        w = min(self.width(), avail.width())
        h = min(self.height(), avail.height())
        self.resize(w, h)
        self.move(
            avail.x() + (avail.width() - w) // 2,
            avail.y() + (avail.height() - h) // 2,
        )
