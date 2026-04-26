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
    is_com_available as ppt_com_available,
)
from .. import licensing as licensing_mod


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

        # Engine status registreren
        register_audio_status(self.controller.audio)
        register_osc_status(self.controller.osc)
        register_osc_out_status(self.controller.osc_out)
        register_video_status(self.controller.video)
        register_image_status(self.controller.image)
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
        # En naar de OSC-output engine voor de "Test verzenden"-knop op
        # Network-cues.
        self.inspector.osc_out_engine = self.controller.osc_out

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
        self._add_action(m_cue, "Nieuwe Afbeelding-cue", lambda: self.action_new_cue(CueType.IMAGE), QKeySequence("Ctrl+0"),
                         tip="Toont een still-image fullscreen op het gekozen scherm (Qt)")
        self._add_action(m_cue, "Nieuwe Presentatie-cue", lambda: self.action_new_cue(CueType.PRESENTATION), QKeySequence("Ctrl+9"),
                         tip="Stuurt een PowerPoint-presentatie aan via COM (Open / Volgende slide / Vorige / Goto / Sluit)")
        self._add_action(m_cue, "Nieuwe Network-cue", lambda: self.action_new_cue(CueType.NETWORK),
                         tip="Stuurt een OSC-message naar een externe ontvanger (Companion, QLab, SQ5, …)")
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
        self._add_action(m_help, "Licentie…", self.action_license,
                         tip="Toont de actieve licentie en laat je een nieuwe importeren")
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

    def _on_network_send_failed(self, cue_id: str, err: str) -> None:
        """Toon een transiënte waarschuwing in de statusbar als een
        Network-cue's OSC-send mislukte. Anders zou de operator pas
        merken dat de trigger niet aankwam doordat de receiver niet
        reageert."""
        cue = self.ws.find(cue_id)
        name = cue.name if cue else cue_id[:8]
        msg = f"⚠ Network-cue '{name}' faalde: {err}"
        # showMessage met timeout 4000ms — verschijnt links in de statusbar.
        self.statusBar().showMessage(msg, 4000)

    def _on_cue_blocked_by_license(self, cue_id: str, cue_type: str) -> None:
        """Een cue is geskipt omdat het cue-type een Pro-licentie vereist.
        Flash een melding in de statusbar — niet een modal, want de show
        moet kunnen doorlopen."""
        cue = self.ws.find(cue_id)
        name = cue.name if cue else cue_id[:8]
        msg = (
            f"🔒 '{name}' ({cue_type}) vereist een Pro-licentie — "
            f"open Help → Licentie…"
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

        added = 0

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
            self.ws.add_cue(cue)
            added += 1

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

            added += self._add_ppt_cues(path, mode)

        if added:
            self.cue_list.refresh()
            self._sync_title()

    def _add_ppt_cues(self, path: Path, mode: str) -> int:
        """Voeg cues voor één PPT-bestand toe op basis van keuze. Geeft
        het aantal toegevoegde cues terug."""
        from ..cues import PresentationAction
        n = len(self.ws.cues) + 1

        if mode == MODE_SINGLE:
            cue = Cue(cue_type=CueType.PRESENTATION, cue_number=str(n),
                      name=path.stem, file_path=str(path),
                      presentation_action=PresentationAction.OPEN)
            self.ws.add_cue(cue)
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

        added = 0
        for i, png in enumerate(png_paths, start=1):
            cue = Cue(
                cue_type=CueType.IMAGE,
                cue_number=str(n + added),
                name=f"{path.stem} — slide {i}",
                file_path=png,
            )
            self.ws.add_cue(cue)
            added += 1
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
