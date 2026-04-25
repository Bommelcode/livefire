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
from ..engines.powerpoint import register_status as register_powerpoint_status
from ..engines.video import register_status as register_video_status

from .cuelist import CueListWidget
from .cuetoolbar import CueToolbar
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
        register_video_status(self.controller.video)
        register_powerpoint_status(self.controller.powerpoint)
        # VLC-audio-device uit QSettings toepassen
        self._apply_video_audio_device_from_settings()

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
        left_layout.addWidget(self.cue_toolbar)

        self.cue_list = CueListWidget(self.ws)
        self.cue_list.cue_selected.connect(self._on_cue_selected)
        self.cue_list.playhead_changed.connect(self._on_playhead_changed)
        self.cue_list.go_requested.connect(self.action_go)
        self.cue_list.files_dropped.connect(self._on_files_dropped)
        left_layout.addWidget(self.cue_list, 1)

        splitter.addWidget(left_side)

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
        m_file.setToolTipsVisible(True)
        self._add_action(m_file, "Nieuw", self.action_new, QKeySequence.StandardKey.New,
                         tip="Maak een nieuwe, lege workspace (sluit de huidige)")
        self._add_action(m_file, "Openen…", self.action_open, QKeySequence.StandardKey.Open,
                         tip="Open een bestaande .livefire workspace van schijf")
        self._add_action(m_file, "Opslaan", self.action_save, QKeySequence.StandardKey.Save,
                         tip="Schrijf de huidige workspace weg (Opslaan als… bij eerste keer)")
        self._add_action(m_file, "Opslaan als…", self.action_save_as, QKeySequence.StandardKey.SaveAs,
                         tip="Sla de workspace op naar een nieuw .livefire bestand")
        m_file.addSeparator()
        self._add_action(m_file, "Voorkeuren…", self.action_preferences, QKeySequence("Ctrl+,"),
                         tip="Audio-device, samplerate en OSC-input instellen")
        m_file.addSeparator()
        self._add_action(m_file, "Afsluiten", self.close, QKeySequence("Ctrl+Q"),
                         tip="Sluit liveFire")

        # Cue
        m_cue = mb.addMenu("&Cue")
        m_cue.setToolTipsVisible(True)
        self._add_action(m_cue, "Nieuwe Audio-cue", lambda: self.action_new_cue(CueType.AUDIO), QKeySequence("Ctrl+1"),
                         tip="Speelt een audio-bestand af met volume, loops en fades")
        self._add_action(m_cue, "Nieuwe Video-cue", lambda: self.action_new_cue(CueType.VIDEO), QKeySequence("Ctrl+8"),
                         tip="Speelt een video-bestand fullscreen af op het gekozen scherm (libVLC)")
        self._add_action(m_cue, "Nieuwe Presentatie-cue", lambda: self.action_new_cue(CueType.PRESENTATION), QKeySequence("Ctrl+9"),
                         tip="Stuurt een PowerPoint-presentatie aan via COM (Open / Volgende slide / Vorige / Goto / Sluit)")
        self._add_action(m_cue, "Nieuwe Fade-cue", lambda: self.action_new_cue(CueType.FADE), QKeySequence("Ctrl+2"),
                         tip="Verandert het volume van een andere (lopende) audio-cue over tijd")
        self._add_action(m_cue, "Nieuwe Wait-cue", lambda: self.action_new_cue(CueType.WAIT), QKeySequence("Ctrl+3"),
                         tip="Pauzeert een vaste tijd in de playback-volgorde")
        self._add_action(m_cue, "Nieuwe Stop-cue", lambda: self.action_new_cue(CueType.STOP), QKeySequence("Ctrl+4"),
                         tip="Stopt een specifieke cue of (leeg target) alles")
        self._add_action(m_cue, "Nieuwe Group-cue", lambda: self.action_new_cue(CueType.GROUP), QKeySequence("Ctrl+5"),
                         tip="Container voor meerdere cues (placeholder in v0.3)")
        self._add_action(m_cue, "Nieuwe Memo-cue", lambda: self.action_new_cue(CueType.MEMO), QKeySequence("Ctrl+6"),
                         tip="Alleen notitie — doet niets bij GO")
        self._add_action(m_cue, "Nieuwe Start-cue", lambda: self.action_new_cue(CueType.START), QKeySequence("Ctrl+7"),
                         tip="Triggert een andere cue bij GO (handig voor re-use)")
        m_cue.addSeparator()
        self._add_action(m_cue, "Verwijderen", self.action_delete_selected, QKeySequence.StandardKey.Delete,
                         tip="Verwijdert de geselecteerde cue(s)")
        self._add_action(m_cue, "Hernummeren", self.action_renumber,
                         tip="Hernummert alle cues oplopend vanaf 1")

        # Transport
        m_tr = mb.addMenu("&Transport")
        m_tr.setToolTipsVisible(True)
        self._add_action(m_tr, "GO", self.action_go, QKeySequence("Space"),
                         tip="Start de cue op de playhead en schuif playhead door")
        self._add_action(m_tr, "Stop All", self.action_stop_all, QKeySequence("Escape"),
                         tip="Stop onmiddellijk alle actieve cues (panic)")

        # Help
        m_help = mb.addMenu("&Help")
        m_help.setToolTipsVisible(True)
        self._add_action(m_help, "Engine-status…", self.action_engine_status,
                         tip="Toont welke engines (Audio, OSC) beschikbaar zijn en hun status")
        self._add_action(m_help, f"Over {APP_NAME}…", self.action_about,
                         tip=f"Over {APP_NAME} — versie en auteur")

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

    def action_preferences(self) -> None:
        dlg = PreferencesDialog(
            self.controller.audio, self.controller.osc,
            self.controller.video, self,
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
                self, "OSC-input niet gestart",
                f"Kon OSC niet starten op poort {port}: {err}",
            )

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

    def _on_running_changed(self) -> None:
        self.transport.set_active_count(len(self.controller.audio.active_cue_ids()))

    # Bestandstype-herkenning voor drag-and-drop. Video en afbeeldingen worden
    # nu als placeholder-Memo ingevoegd (echte cue-types komen in v0.6.0).
    _AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif", ".m4a"}
    _VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif"}
    _PPT_EXTS = {".pptx", ".ppt", ".pptm"}

    def _on_files_dropped(self, paths: list[str]) -> None:
        from ..cues import PresentationAction
        added = 0
        for p in paths:
            path = Path(p)
            ext = path.suffix.lower()
            n = len(self.ws.cues) + 1
            if ext in self._AUDIO_EXTS:
                cue = Cue(cue_type=CueType.AUDIO, cue_number=str(n),
                          name=path.stem, file_path=str(path))
            elif ext in self._VIDEO_EXTS:
                cue = Cue(cue_type=CueType.VIDEO, cue_number=str(n),
                          name=path.stem, file_path=str(path))
            elif ext in self._PPT_EXTS:
                cue = Cue(cue_type=CueType.PRESENTATION, cue_number=str(n),
                          name=path.stem, file_path=str(path),
                          presentation_action=PresentationAction.OPEN)
            elif ext in self._IMAGE_EXTS:
                cue = Cue(
                    cue_type=CueType.MEMO, cue_number=str(n), name=path.stem,
                    notes=(f"[Afbeelding-placeholder] {path}\n\n"
                           "Image-cue-type is nog niet geïmplementeerd — "
                           "bewaar als Memo."),
                )
            else:
                continue
            self.ws.add_cue(cue)
            added += 1
        if added:
            self.cue_list.refresh()
            self._sync_title()

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
