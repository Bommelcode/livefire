"""Inspector: rechterpaneel met type-afhankelijke form-velden voor de
geselecteerde cue. Zit in een QScrollArea zodat velden op kleine schermen
niet samengedrukt worden (zelfde les als v0.2)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox,
    QComboBox, QPlainTextEdit, QGroupBox, QScrollArea, QPushButton, QFileDialog,
    QCheckBox, QHBoxLayout, QLabel,
)

from ..cues import Cue, CueType, ContinueMode
from ..workspace import Workspace


class InspectorWidget(QWidget):
    """Toont en wijzigt de eigenschappen van één cue."""

    cue_changed = pyqtSignal(object)   # Cue

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.cue: Cue | None = None
        self._updating = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)

        self.content = QWidget()
        self.scroll.setWidget(self.content)
        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Header
        self.header = QLabel("Geen cue geselecteerd")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        self.header.setFont(f)
        lay.addWidget(self.header)

        # ---- Basis-groep ---------------------------------------------------
        grp_basic = QGroupBox("Algemeen")
        form = QFormLayout(grp_basic)
        self.ed_number = QLineEdit()
        self.ed_name = QLineEdit()
        self.cb_type = QComboBox()
        self.cb_type.addItems(CueType.ALL)
        self.ed_color = QLineEdit()
        self.ed_color.setPlaceholderText("#3aa2e6 of leeg")
        form.addRow("Nummer", self.ed_number)
        form.addRow("Type", self.cb_type)
        form.addRow("Naam", self.ed_name)
        form.addRow("Kleur", self.ed_color)
        lay.addWidget(grp_basic)

        # ---- Timing --------------------------------------------------------
        grp_timing = QGroupBox("Timing")
        fl = QFormLayout(grp_timing)
        self.sp_pre = self._spin_seconds()
        self.sp_dur = self._spin_seconds(max_val=36000.0)
        self.sp_post = self._spin_seconds()
        self.cb_continue = QComboBox()
        for k, v in ContinueMode.LABELS.items():
            self.cb_continue.addItem(v, k)
        fl.addRow("Pre-wait (s)", self.sp_pre)
        fl.addRow("Duration (s)", self.sp_dur)
        fl.addRow("Post-wait (s)", self.sp_post)
        fl.addRow("Continue", self.cb_continue)
        lay.addWidget(grp_timing)

        # ---- Audio ---------------------------------------------------------
        self.grp_audio = QGroupBox("Audio")
        al = QFormLayout(self.grp_audio)
        path_row = QHBoxLayout()
        self.ed_path = QLineEdit()
        self.btn_browse = QPushButton("Bladeren…")
        self.btn_browse.clicked.connect(self._browse_file)
        path_row.addWidget(self.ed_path)
        path_row.addWidget(self.btn_browse)
        path_container = QWidget()
        path_container.setLayout(path_row)
        al.addRow("Bestand", path_container)
        self.sp_volume = self._spin(-96.0, 12.0, 0.1, " dB")
        self.sp_loops = QSpinBox()
        self.sp_loops.setRange(0, 9999)
        self.sp_loops.setSpecialValueText("∞")
        self.sp_start = self._spin_seconds()
        self.sp_end = self._spin_seconds()
        al.addRow("Volume", self.sp_volume)
        al.addRow("Loops (0 = ∞)", self.sp_loops)
        al.addRow("Start-offset (s)", self.sp_start)
        al.addRow("Eind-offset (s)", self.sp_end)
        lay.addWidget(self.grp_audio)

        # ---- Wait ----------------------------------------------------------
        self.grp_wait = QGroupBox("Wait")
        wl = QFormLayout(self.grp_wait)
        self.sp_wait = self._spin_seconds(max_val=3600.0)
        wl.addRow("Wacht-duur (s)", self.sp_wait)
        lay.addWidget(self.grp_wait)

        # ---- Target (Stop / Fade / Start) ---------------------------------
        self.grp_target = QGroupBox("Doel")
        tl = QFormLayout(self.grp_target)
        self.cb_target = QComboBox()
        tl.addRow("Target-cue", self.cb_target)
        self.sp_fade_target = self._spin(-96.0, 12.0, 0.1, " dB")
        self.chk_fade_stops = QCheckBox("Target stoppen na fade")
        tl.addRow("Fade naar", self.sp_fade_target)
        tl.addRow("", self.chk_fade_stops)
        lay.addWidget(self.grp_target)

        # ---- Notities ------------------------------------------------------
        grp_notes = QGroupBox("Notities")
        nl = QVBoxLayout(grp_notes)
        self.ed_notes = QPlainTextEdit()
        self.ed_notes.setMinimumHeight(60)
        nl.addWidget(self.ed_notes)
        lay.addWidget(grp_notes)

        lay.addStretch(1)

        # ---- wire changes --------------------------------------------------
        for w in (self.ed_number, self.ed_name, self.ed_color, self.ed_path,
                  self.ed_notes):
            if isinstance(w, QPlainTextEdit):
                w.textChanged.connect(self._on_any_change)
            else:
                w.textChanged.connect(self._on_any_change)
        for w in (self.sp_pre, self.sp_dur, self.sp_post, self.sp_volume,
                  self.sp_start, self.sp_end, self.sp_wait, self.sp_fade_target):
            w.valueChanged.connect(self._on_any_change)
        self.sp_loops.valueChanged.connect(self._on_any_change)
        self.cb_type.currentTextChanged.connect(self._on_type_change)
        self.cb_continue.currentIndexChanged.connect(self._on_any_change)
        self.cb_target.currentIndexChanged.connect(self._on_any_change)
        self.chk_fade_stops.toggled.connect(self._on_any_change)

        self.set_cue(None)

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _spin(lo: float, hi: float, step: float, suffix: str = "") -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(2)
        if suffix:
            s.setSuffix(suffix)
        return s

    @classmethod
    def _spin_seconds(cls, max_val: float = 3600.0) -> QDoubleSpinBox:
        return cls._spin(0.0, max_val, 0.1, " s")

    # ---- data binding ------------------------------------------------------

    def refresh_targets(self) -> None:
        """Ververs de target-cue dropdown (bv. na toevoegen/verwijderen)."""
        self._updating = True
        current = self.cb_target.currentData()
        self.cb_target.clear()
        self.cb_target.addItem("— alles / geen —", "")
        for c in self.workspace.cues:
            label = f"{c.cue_number or '?'}: {c.name or '(naamloos)'} [{c.cue_type}]"
            if self.cue is not None and c.id == self.cue.id:
                continue  # niet naar jezelf verwijzen
            self.cb_target.addItem(label, c.id)
        # Restore
        idx = self.cb_target.findData(current)
        if idx >= 0:
            self.cb_target.setCurrentIndex(idx)
        self._updating = False

    def set_cue(self, cue: Cue | None) -> None:
        self._updating = True
        self.cue = cue

        if cue is None:
            self.header.setText("Geen cue geselecteerd")
            self.grp_audio.setVisible(False)
            self.grp_wait.setVisible(False)
            self.grp_target.setVisible(False)
            self.content.setEnabled(False)
            self._updating = False
            return

        self.content.setEnabled(True)
        self.header.setText(f"{cue.cue_number or '?'}: {cue.name or '(naamloos)'}")

        self.ed_number.setText(cue.cue_number)
        self.ed_name.setText(cue.name)
        self.cb_type.setCurrentText(cue.cue_type)
        self.ed_color.setText(cue.color)

        self.sp_pre.setValue(cue.pre_wait)
        self.sp_dur.setValue(cue.duration)
        self.sp_post.setValue(cue.post_wait)
        idx = self.cb_continue.findData(cue.continue_mode)
        if idx >= 0:
            self.cb_continue.setCurrentIndex(idx)

        self.ed_path.setText(cue.file_path)
        self.sp_volume.setValue(cue.volume_db)
        self.sp_loops.setValue(cue.loops)
        self.sp_start.setValue(cue.audio_start_offset)
        self.sp_end.setValue(cue.audio_end_offset)
        self.sp_wait.setValue(cue.wait_duration)
        self.sp_fade_target.setValue(cue.fade_target_db)
        self.chk_fade_stops.setChecked(cue.fade_stops_target)
        self.ed_notes.setPlainText(cue.notes)

        self.refresh_targets()
        idx = self.cb_target.findData(cue.target_cue_id)
        if idx >= 0:
            self.cb_target.setCurrentIndex(idx)

        self._update_visibility(cue.cue_type)
        self._updating = False

    def _update_visibility(self, cue_type: str) -> None:
        self.grp_audio.setVisible(cue_type == CueType.AUDIO)
        self.grp_wait.setVisible(cue_type == CueType.WAIT)
        self.grp_target.setVisible(cue_type in (CueType.STOP, CueType.FADE, CueType.START))

    # ---- events ------------------------------------------------------------

    def _on_type_change(self, new_type: str) -> None:
        self._update_visibility(new_type)
        self._on_any_change()

    def _on_any_change(self) -> None:
        if self._updating or self.cue is None:
            return
        c = self.cue
        c.cue_number = self.ed_number.text()
        c.name = self.ed_name.text()
        c.cue_type = self.cb_type.currentText()
        c.color = self.ed_color.text().strip()
        c.pre_wait = self.sp_pre.value()
        c.duration = self.sp_dur.value()
        c.post_wait = self.sp_post.value()
        c.continue_mode = self.cb_continue.currentData()
        c.file_path = self.ed_path.text()
        c.volume_db = self.sp_volume.value()
        c.loops = self.sp_loops.value()
        c.audio_start_offset = self.sp_start.value()
        c.audio_end_offset = self.sp_end.value()
        c.wait_duration = self.sp_wait.value()
        c.fade_target_db = self.sp_fade_target.value()
        c.fade_stops_target = self.chk_fade_stops.isChecked()
        c.target_cue_id = self.cb_target.currentData() or ""
        c.notes = self.ed_notes.toPlainText()
        self.workspace.dirty = True
        self.cue_changed.emit(c)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Kies audio-bestand", "",
            "Audio (*.wav *.mp3 *.flac *.ogg *.aiff *.aif);;Alle bestanden (*)",
        )
        if path:
            self.ed_path.setText(path)
