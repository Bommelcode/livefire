"""Inspector: rechterpaneel met type-afhankelijke form-velden voor de
geselecteerde cue. Zit in een QScrollArea zodat velden op kleine schermen
niet samengedrukt worden (zelfde les als v0.2)."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox,
    QComboBox, QPlainTextEdit, QGroupBox, QScrollArea, QPushButton, QFileDialog,
    QCheckBox, QHBoxLayout, QLabel,
)

from ..cues import Cue, CueType, ContinueMode
from ..workspace import Workspace
from .style import CUE_COLORS


def _swatch_icon(hex_color: str, size: int = 14) -> QIcon:
    """Maak een vierkant kleur-swatch als QIcon voor de dropdown."""
    pm = QPixmap(size, size)
    if hex_color:
        pm.fill(QColor(hex_color))
    else:
        pm.fill(QColor(0, 0, 0, 0))  # transparant voor "Geen"
    return QIcon(pm)


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
        self.ed_number.setToolTip("Cue-nummer zoals getoond in de cuelist. Vrij tekstveld (mag letters bevatten).")
        self.ed_name = QLineEdit()
        self.ed_name.setToolTip("Korte beschrijving voor jezelf. Heeft geen invloed op playback.")
        self.cb_type = QComboBox()
        self.cb_type.addItems(CueType.ALL)
        self.cb_type.setToolTip(
            "Type van de cue:\n"
            "• Audio — speelt een bestand\n"
            "• Fade — verandert het volume van een andere audio-cue\n"
            "• Wait — pauzeert voor een bepaalde tijd\n"
            "• Stop — stopt een specifieke cue of alles\n"
            "• Start — triggert een andere cue\n"
            "• Group — container (placeholder in v0.3)\n"
            "• Memo — alleen notitie, geen actie"
        )
        self.cb_color = QComboBox()
        self.cb_color.setIconSize(QSize(14, 14))
        self.cb_color.setToolTip("Kleurtag die in de cuelist als balk zichtbaar wordt.")
        for label, hex_color in CUE_COLORS:
            self.cb_color.addItem(_swatch_icon(hex_color), label, hex_color)
        form.addRow("Nummer", self.ed_number)
        form.addRow("Type", self.cb_type)
        form.addRow("Naam", self.ed_name)
        form.addRow("Kleur", self.cb_color)
        lay.addWidget(grp_basic)

        # ---- Timing --------------------------------------------------------
        grp_timing = QGroupBox("Timing")
        fl = QFormLayout(grp_timing)
        self.sp_pre = self._spin_seconds()
        self.sp_pre.setToolTip("Wachttijd tussen GO en het daadwerkelijk starten van deze cue.")
        self.sp_dur = self._spin_seconds(max_val=36000.0)
        self.sp_dur.setToolTip("Hoe lang de actie duurt. Voor Audio: 0 = speel tot het bestand op is.")
        self.sp_post = self._spin_seconds()
        self.sp_post.setToolTip("Wachttijd nadat de actie klaar is, vóór de cue 'finished' wordt.")
        self.cb_continue = QComboBox()
        for k, v in ContinueMode.LABELS.items():
            self.cb_continue.addItem(v, k)
        self.cb_continue.setToolTip(
            "Hoe de playback doorgaat:\n"
            "• Do Not Continue — stopt na deze cue\n"
            "• Auto-Continue — volgende cue start zodra deze z'n actie start\n"
            "• Auto-Follow — volgende cue start nadat deze klaar is"
        )
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
        self.ed_path.setToolTip("Pad naar het audio-bestand (wav/mp3/flac/ogg/aiff).")
        self.btn_browse = QPushButton("Bladeren…")
        self.btn_browse.setToolTip("Open een bestand-dialog om een audio-bestand te kiezen.")
        self.btn_browse.clicked.connect(self._browse_file)
        path_row.addWidget(self.ed_path)
        path_row.addWidget(self.btn_browse)
        path_container = QWidget()
        path_container.setLayout(path_row)
        al.addRow("Bestand", path_container)
        self.sp_volume = self._spin(-96.0, 12.0, 0.1, " dB")
        self.sp_volume.setToolTip("Afspeelvolume in dB. 0 dB = origineel, −6 dB = halve amplitude.")
        self.sp_loops = QSpinBox()
        self.sp_loops.setRange(0, 9999)
        self.sp_loops.setSpecialValueText("∞")
        self.sp_loops.setToolTip("Hoe vaak het bestand afspelen. 0 = oneindig loopen.")
        self.sp_start = self._spin_seconds()
        self.sp_start.setToolTip("Seconden die je vanaf het begin van het bestand overslaat.")
        self.sp_end = self._spin_seconds()
        self.sp_end.setToolTip("Seconden die je van het einde van het bestand afsnijdt.")
        self.sp_fade_in = self._spin_seconds(max_val=600.0)
        self.sp_fade_in.setToolTip("Fade-in tijd. Cue start op stilte en rampt naar het ingestelde volume.")
        self.sp_fade_out = self._spin_seconds(max_val=600.0)
        self.sp_fade_out.setToolTip(
            "Fade-out tijd aan het einde van de cue. Bij AUTO_FOLLOW start de "
            "volgende cue gelijktijdig met de fade-out — dat geeft een natuurlijke "
            "crossfade."
        )
        al.addRow("Volume", self.sp_volume)
        al.addRow("Loops (0 = ∞)", self.sp_loops)
        al.addRow("Start-offset (s)", self.sp_start)
        al.addRow("Eind-offset (s)", self.sp_end)
        al.addRow("Fade-in (s)", self.sp_fade_in)
        al.addRow("Fade-out (s)", self.sp_fade_out)
        lay.addWidget(self.grp_audio)

        # ---- Wait ----------------------------------------------------------
        self.grp_wait = QGroupBox("Wait")
        wl = QFormLayout(self.grp_wait)
        self.sp_wait = self._spin_seconds(max_val=3600.0)
        self.sp_wait.setToolTip("Hoe lang deze Wait-cue pauzeert voor de playback doorgaat.")
        wl.addRow("Wacht-duur (s)", self.sp_wait)
        lay.addWidget(self.grp_wait)

        # ---- Target (Stop / Fade / Start) ---------------------------------
        self.grp_target = QGroupBox("Doel")
        tl = QFormLayout(self.grp_target)
        self.cb_target = QComboBox()
        self.cb_target.setToolTip(
            "De cue waar deze Stop/Fade/Start op werkt. Voor Stop: leeg = alles stoppen."
        )
        tl.addRow("Target-cue", self.cb_target)
        self.sp_fade_target = self._spin(-96.0, 12.0, 0.1, " dB")
        self.sp_fade_target.setToolTip("Het volume waar de Fade naartoe gaat (voor Fade-cues).")
        self.chk_fade_stops = QCheckBox("Target stoppen na fade")
        self.chk_fade_stops.setToolTip(
            "Zet aan om de target-cue te stoppen zodra de fade-out −∞ dB raakt."
        )
        tl.addRow("Fade naar", self.sp_fade_target)
        tl.addRow("", self.chk_fade_stops)
        lay.addWidget(self.grp_target)

        # ---- Triggers ------------------------------------------------------
        self.grp_triggers = QGroupBox("Triggers")
        trg = QFormLayout(self.grp_triggers)
        osc_row = QHBoxLayout()
        self.ed_trigger_osc = QLineEdit()
        self.ed_trigger_osc.setPlaceholderText("/livefire/go/intro — leeg = geen trigger")
        self.ed_trigger_osc.setToolTip(
            "OSC-address dat deze cue afvuurt wanneer het binnenkomt op de OSC-input "
            "poort (instelbaar in Voorkeuren). Leeg = geen externe trigger."
        )
        self.btn_learn_osc = QPushButton("Learn…")
        self.btn_learn_osc.setToolTip(
            "Wacht op de eerstvolgende OSC-message en vul het address automatisch in. "
            "OSC-input moet aan staan."
        )
        self.btn_learn_osc.clicked.connect(self._learn_osc)
        osc_row.addWidget(self.ed_trigger_osc)
        osc_row.addWidget(self.btn_learn_osc)
        osc_container = QWidget()
        osc_container.setLayout(osc_row)
        trg.addRow("OSC-address", osc_container)
        lay.addWidget(self.grp_triggers)

        # ---- Notities ------------------------------------------------------
        grp_notes = QGroupBox("Notities")
        nl = QVBoxLayout(grp_notes)
        self.ed_notes = QPlainTextEdit()
        self.ed_notes.setMinimumHeight(60)
        self.ed_notes.setToolTip("Vrije notities voor jezelf. Zichtbaar in Memo-cues.")
        nl.addWidget(self.ed_notes)
        lay.addWidget(grp_notes)

        lay.addStretch(1)

        # ---- wire changes --------------------------------------------------
        for w in (self.ed_number, self.ed_name, self.ed_path, self.ed_notes,
                  self.ed_trigger_osc):
            if isinstance(w, QPlainTextEdit):
                w.textChanged.connect(self._on_any_change)
            else:
                w.textChanged.connect(self._on_any_change)
        for w in (self.sp_pre, self.sp_dur, self.sp_post, self.sp_volume,
                  self.sp_start, self.sp_end, self.sp_fade_in, self.sp_fade_out,
                  self.sp_wait, self.sp_fade_target):
            w.valueChanged.connect(self._on_any_change)
        self.sp_loops.valueChanged.connect(self._on_any_change)
        self.cb_type.currentTextChanged.connect(self._on_type_change)
        self.cb_continue.currentIndexChanged.connect(self._on_any_change)
        self.cb_target.currentIndexChanged.connect(self._on_any_change)
        self.cb_color.currentIndexChanged.connect(self._on_any_change)
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
        self._select_color(cue.color)

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
        self.sp_fade_in.setValue(cue.audio_fade_in)
        self.sp_fade_out.setValue(cue.audio_fade_out)
        self.sp_wait.setValue(cue.wait_duration)
        self.sp_fade_target.setValue(cue.fade_target_db)
        self.chk_fade_stops.setChecked(cue.fade_stops_target)
        self.ed_trigger_osc.setText(cue.trigger_osc)
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
        c.color = self.cb_color.currentData() or ""
        c.pre_wait = self.sp_pre.value()
        c.duration = self.sp_dur.value()
        c.post_wait = self.sp_post.value()
        c.continue_mode = self.cb_continue.currentData()
        c.file_path = self.ed_path.text()
        c.volume_db = self.sp_volume.value()
        c.loops = self.sp_loops.value()
        c.audio_start_offset = self.sp_start.value()
        c.audio_end_offset = self.sp_end.value()
        c.audio_fade_in = self.sp_fade_in.value()
        c.audio_fade_out = self.sp_fade_out.value()
        c.wait_duration = self.sp_wait.value()
        c.fade_target_db = self.sp_fade_target.value()
        c.fade_stops_target = self.chk_fade_stops.isChecked()
        c.target_cue_id = self.cb_target.currentData() or ""
        c.trigger_osc = self.ed_trigger_osc.text().strip()
        c.notes = self.ed_notes.toPlainText()
        self.workspace.dirty = True
        self.cue_changed.emit(c)

    def _select_color(self, hex_color: str) -> None:
        """Selecteer de juiste preset in cb_color. Als hex_color geen preset is
        (bv. geërfd uit oudere workspace), voeg hem tijdelijk toe als 'Aangepast'."""
        idx = self.cb_color.findData(hex_color)
        if idx < 0 and hex_color:
            self.cb_color.addItem(
                _swatch_icon(hex_color),
                f"Aangepast ({hex_color})",
                hex_color,
            )
            idx = self.cb_color.count() - 1
        if idx < 0:
            idx = 0  # "Geen"
        self.cb_color.setCurrentIndex(idx)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Kies audio-bestand", "",
            "Audio (*.wav *.mp3 *.flac *.ogg *.aiff *.aif);;Alle bestanden (*)",
        )
        if path:
            # Check vóór we het pad updaten of de naam auto-gegenereerd is.
            # Drie gevallen waarin we de naam willen (her-)vullen:
            #   1. leeg
            #   2. een default "{CueType} {n}" (ook als de cue-type inmiddels
            #      is veranderd)
            #   3. gelijk aan de stem van het huidige bestand (dan was 'ie
            #      eerder auto-gevuld en willen we bij file-vervanging mee)
            old_path = self.ed_path.text().strip()
            name = self.ed_name.text().strip()
            auto_default = bool(re.match(
                r"^(?:" + "|".join(CueType.ALL) + r") \d+$", name
            ))
            from_old_file = bool(old_path) and name == Path(old_path).stem
            should_fill = not name or auto_default or from_old_file

            self.ed_path.setText(path)
            if should_fill:
                self.ed_name.setText(Path(path).stem)

    # ---- trigger-learn ----------------------------------------------------

    osc_engine = None  # wordt door MainWindow gezet: inspector.osc_engine = …

    def _learn_osc(self) -> None:
        """Open een modal die wacht op de volgende OSC-message en 'm invult."""
        from .dialogs.trigger_learn import OscLearnDialog
        if self.osc_engine is None or not self.osc_engine.running:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "OSC niet actief",
                "De OSC-input engine draait niet. Zet 'm aan via Voorkeuren…"
                " en stuur dan nogmaals.",
            )
            return
        dlg = OscLearnDialog(self.osc_engine, self)
        if dlg.exec() and dlg.learned_address:
            self.ed_trigger_osc.setText(dlg.learned_address)
