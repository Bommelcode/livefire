"""Hoofdvenster — integreert cue-list, inspector, transport, menu's en
shortcuts met de PlaybackController."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QFileDialog,
    QMessageBox, QStatusBar, QLabel,
)

from .. import APP_NAME, APP_VERSION, WORKSPACE_EXT
from ..cues import Cue, CueType
from ..workspace import Workspace
from ..playback import PlaybackController
from ..engines import registry
from ..engines.audio import (
    register_status as register_audio_status,
    find_device_index_by_name,
)
from ..engines.osc import register_status as register_osc_status

from .cuelist import CueListWidget
from .inspector import InspectorWidget
from .transport import TransportWidget
from .dialogs import show_about, EngineStatusDialog, PreferencesDialog
from .dialogs.preferences import DEFAULT_SAMPLE_RATE, DEFAULT_OSC_PORT


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1400, 860)

        # Model
        self.ws = Workspace()

        # Audio-engine configureren vanuit QSettings (device + samplerate)
        # vóórdat de controller hem start.
        audio = self._build_audio_engine_from_settings()

        # Playback
        self.controller = PlaybackController(self.ws, parent=self, audio=audio)
        self.controller.cue_state_changed.connect(self._on_cue_state_changed)
        self.controller.running_changed.connect(self._on_running_changed)

        # OSC-input opstarten vanuit QSettings
        self._start_osc_from_settings()

        # Engine status registreren
        register_audio_status(self.controller.audio)
        register_osc_status(self.controller.osc)

        # UI
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._sync_title()

        # Inspector krijgt een handle naar de OSC-engine voor de Learn-dialog
        self.inspector.osc_engine = self.controller.osc

    # ---- build ------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        vroot = QVBoxLayout(central)
        vroot.setContentsMargins(0, 0, 0, 0)
        vroot.setSpacing(0)

        self.transport = TransportWidget()
        self.transport.go_clicked.connect(self.action_go)
        self.transport.stop_all_clicked.connect(self.action_stop_all)
        vroot.addWidget(self.transport)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        vroot.addWidget(splitter, 1)

        self.cue_list = CueListWidget(self.ws)
        self.cue_list.cue_selected.connect(self._on_cue_selected)
        self.cue_list.playhead_changed.connect(self._on_playhead_changed)
        self.cue_list.go_requested.connect(self.action_go)
        splitter.addWidget(self.cue_list)

        self.inspector = InspectorWidget(self.ws)
        self.inspector.cue_changed.connect(self._on_inspector_changed)
        splitter.addWidget(self.inspector)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([820, 580])

        # Statusbar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel("")
        sb.addPermanentWidget(self.status_label)
        self._refresh_statusbar()

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # File
        m_file = mb.addMenu("&Bestand")
        self._add_action(m_file, "Nieuw", self.action_new, QKeySequence.StandardKey.New)
        self._add_action(m_file, "Openen…", self.action_open, QKeySequence.StandardKey.Open)
        self._add_action(m_file, "Opslaan", self.action_save, QKeySequence.StandardKey.Save)
        self._add_action(m_file, "Opslaan als…", self.action_save_as, QKeySequence.StandardKey.SaveAs)
        m_file.addSeparator()
        self._add_action(m_file, "Voorkeuren…", self.action_preferences, QKeySequence("Ctrl+,"))
        m_file.addSeparator()
        self._add_action(m_file, "Afsluiten", self.close, QKeySequence("Ctrl+Q"))

        # Cue
        m_cue = mb.addMenu("&Cue")
        self._add_action(m_cue, "Nieuwe Audio-cue", lambda: self.action_new_cue(CueType.AUDIO), QKeySequence("Ctrl+1"))
        self._add_action(m_cue, "Nieuwe Fade-cue", lambda: self.action_new_cue(CueType.FADE), QKeySequence("Ctrl+2"))
        self._add_action(m_cue, "Nieuwe Wait-cue", lambda: self.action_new_cue(CueType.WAIT), QKeySequence("Ctrl+3"))
        self._add_action(m_cue, "Nieuwe Stop-cue", lambda: self.action_new_cue(CueType.STOP), QKeySequence("Ctrl+4"))
        self._add_action(m_cue, "Nieuwe Group-cue", lambda: self.action_new_cue(CueType.GROUP), QKeySequence("Ctrl+5"))
        self._add_action(m_cue, "Nieuwe Memo-cue", lambda: self.action_new_cue(CueType.MEMO), QKeySequence("Ctrl+6"))
        self._add_action(m_cue, "Nieuwe Start-cue", lambda: self.action_new_cue(CueType.START), QKeySequence("Ctrl+7"))
        m_cue.addSeparator()
        self._add_action(m_cue, "Verwijderen", self.action_delete_selected, QKeySequence.StandardKey.Delete)
        self._add_action(m_cue, "Hernummeren", self.action_renumber)

        # Transport
        m_tr = mb.addMenu("&Transport")
        self._add_action(m_tr, "GO", self.action_go, QKeySequence("Space"))
        self._add_action(m_tr, "Stop All", self.action_stop_all, QKeySequence("Escape"))

        # Help
        m_help = mb.addMenu("&Help")
        self._add_action(m_help, "Engine-status…", self.action_engine_status)
        self._add_action(m_help, f"Over {APP_NAME}…", self.action_about)

    def _build_shortcuts(self) -> None:
        # QAction-shortcuts werken met widget-focus conflict soms niet; deze
        # werken window-wide.
        for key, fn in [
            ("Space", self.action_go),
            ("Escape", self.action_stop_all),
        ]:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)

    @staticmethod
    def _add_action(menu, text, slot, shortcut=None) -> QAction:
        a = QAction(text, menu)
        if shortcut is not None:
            a.setShortcut(shortcut)
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
            self, "Workspace openen", "",
            f"liveFire workspace (*{WORKSPACE_EXT});;Alle bestanden (*)",
        )
        if not path:
            return
        try:
            ws = Workspace.load(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Kan niet openen", str(e))
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
            QMessageBox.critical(self, "Kan niet opslaan", str(e))
            return
        self._sync_title()

    def action_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Workspace opslaan als", "",
            f"liveFire workspace (*{WORKSPACE_EXT})",
        )
        if not path:
            return
        if not path.endswith(WORKSPACE_EXT):
            path += WORKSPACE_EXT
        try:
            self.ws.save(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Kan niet opslaan", str(e))
            return
        self._sync_title()

    # ---- actions: cue -----------------------------------------------------

    def action_new_cue(self, cue_type: str) -> None:
        n = len(self.ws.cues) + 1
        cue = Cue(cue_type=cue_type, cue_number=str(n), name=f"{cue_type} {n}")
        # Invoegen achter huidige selectie
        sel = self.cue_list.selected_cues()
        if sel:
            idx = self.ws.index_of(sel[-1].id) + 1
            self.ws.add_cue(cue, index=idx)
        else:
            self.ws.add_cue(cue)
        self.cue_list.refresh()
        self.cue_list.select_cue(cue.id)
        self._sync_title()

    def action_delete_selected(self) -> None:
        cues = self.cue_list.selected_cues()
        if not cues:
            return
        for c in cues:
            self.controller.stop_cue(c.id)
            self.ws.remove_cue(c.id)
        self.cue_list.refresh()
        self.inspector.set_cue(None)
        self._sync_title()

    def action_renumber(self) -> None:
        self.ws.renumber()
        self.cue_list.refresh()
        self._sync_title()

    # ---- actions: transport -----------------------------------------------

    def action_go(self) -> None:
        if self.controller.playhead_index >= len(self.ws.cues):
            return
        self.controller.go()
        self.cue_list.set_playhead(self.controller.playhead_index)

    def action_stop_all(self) -> None:
        self.controller.stop_all()

    # ---- actions: help ----------------------------------------------------

    def action_engine_status(self) -> None:
        dlg = EngineStatusDialog(self)
        dlg.exec()

    def action_preferences(self) -> None:
        dlg = PreferencesDialog(self.controller.audio, self.controller.osc, self)
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

    def _start_osc_from_settings(self) -> None:
        s = QSettings()
        if not s.value("osc/enabled", False, type=bool):
            return
        port = s.value("osc/port", DEFAULT_OSC_PORT, type=int)
        ok, err = self.controller.osc.start(int(port))
        if not ok:
            QMessageBox.warning(
                self, "OSC-input niet gestart",
                f"Kon OSC niet starten op poort {port}: {err}",
            )

    # ---- reactive handlers ------------------------------------------------

    def _on_cue_selected(self, cue: Cue | None) -> None:
        self.inspector.set_cue(cue)

    def _on_inspector_changed(self, _cue: Cue) -> None:
        self.cue_list.refresh()
        self._sync_title()

    def _on_cue_state_changed(self, cue_id: str) -> None:
        self.cue_list.update_cue(cue_id)

    def _on_running_changed(self) -> None:
        self.transport.set_active_count(len(self.controller.audio.active_cue_ids()))

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
            self.status_label.setText("Alle engines OK")

    def _sync_title(self) -> None:
        name = self.ws.path.name if self.ws.path else "Untitled"
        dirty = "*" if self.ws.dirty else ""
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — {name}{dirty}")

    def _confirm_discard(self) -> bool:
        if not self.ws.dirty:
            return True
        r = QMessageBox.question(
            self, "Niet-opgeslagen wijzigingen",
            "Er zijn niet-opgeslagen wijzigingen. Doorgaan en wijzigingen weggooien?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return r == QMessageBox.StandardButton.Discard

    def closeEvent(self, e) -> None:
        if not self._confirm_discard():
            e.ignore()
            return
        self.controller.shutdown()
        super().closeEvent(e)
