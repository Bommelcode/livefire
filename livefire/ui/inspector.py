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
from ..engines.video import list_screens
from ..workspace import Workspace
from .style import CUE_COLORS
from .video_preview import VideoPreviewWidget


def _swatch_icon(hex_color: str, size: int = 14) -> QIcon:
    """Maak een vierkant kleur-swatch als QIcon voor de dropdown."""
    pm = QPixmap(size, size)
    if hex_color:
        pm.fill(QColor(hex_color))
    else:
        pm.fill(QColor(0, 0, 0, 0))  # transparant voor "Geen"
    return QIcon(pm)


class InspectorWidget(QWidget):
    """Toont en wijzigt de eigenschappen van één of meer geselecteerde cues.

    Bij multi-select worden bulk-veilige velden (kleur, timing, volume,
    fades, continue-mode) toegepast op alle geselecteerden; per-cue velden
    (naam, nummer, bestand, notities, target, trigger-OSC) zijn dan
    uitgeschakeld."""

    cue_changed = pyqtSignal(object)   # Cue

    # Velden die alleen op één cue logisch zijn. Bij multi-select worden
    # de bijbehorende widgets uitgeschakeld.
    _PER_CUE_ATTRS = frozenset({
        "cue_number", "name", "file_path", "notes", "target_cue_id",
        "trigger_osc",
        # Trim-punten zijn bestand-specifiek; bulk-edit zou van één bestand
        # naar ander bestand niet-zinvolle waardes toepassen.
        "video_start_offset", "video_end_offset",
    })

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.cues: list[Cue] = []
        self.cue: Cue | None = None  # eerste geselecteerde, compat voor
                                      # refresh_targets / _learn_osc
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

        # ---- Video ---------------------------------------------------------
        self.grp_video = QGroupBox("Video")
        vl = QFormLayout(self.grp_video)
        video_path_row = QHBoxLayout()
        self.ed_video_path = QLineEdit()
        self.ed_video_path.setToolTip("Pad naar het video-bestand.")
        self.btn_browse_video = QPushButton("Bladeren…")
        self.btn_browse_video.setToolTip("Kies een videobestand.")
        self.btn_browse_video.clicked.connect(self._browse_video)
        video_path_row.addWidget(self.ed_video_path)
        video_path_row.addWidget(self.btn_browse_video)
        vpc = QWidget()
        vpc.setLayout(video_path_row)
        vl.addRow("Bestand", vpc)
        self.cb_video_screen = QComboBox()
        self.cb_video_screen.setToolTip(
            "Monitor waarop deze cue fullscreen wordt weergegeven."
        )
        for idx, label in list_screens():
            self.cb_video_screen.addItem(label, idx)
        vl.addRow("Output-scherm", self.cb_video_screen)
        self.sp_video_fade_in = self._spin_seconds(max_val=600.0)
        self.sp_video_fade_in.setToolTip("Fade-in vanuit zwart.")
        self.sp_video_fade_out = self._spin_seconds(max_val=600.0)
        self.sp_video_fade_out.setToolTip("Fade-to-black aan het einde van de cue.")
        vl.addRow("Fade-in (s)", self.sp_video_fade_in)
        vl.addRow("Fade-out (s)", self.sp_video_fade_out)

        # Thumbnail + timeline voor in/uit-punt scrubbing.
        self.video_preview = VideoPreviewWidget()
        vl.addRow(self.video_preview)

        self.sp_video_in = self._spin_seconds(max_val=36000.0)
        self.sp_video_in.setToolTip("In-punt (vanaf welk moment wordt afgespeeld).")
        self.sp_video_out = self._spin_seconds(max_val=36000.0)
        self.sp_video_out.setToolTip("Uit-punt (waar de cue eindigt). 0 = tot einde bestand.")
        vl.addRow("In-punt (s)", self.sp_video_in)
        vl.addRow("Uit-punt (s)", self.sp_video_out)

        # Bidirectionele sync tussen timeline (drag) en spinboxes (veld).
        self.video_preview.in_point_changed.connect(self._set_video_in_from_timeline)
        self.video_preview.out_point_changed.connect(self._set_video_out_from_timeline)
        self.video_preview.duration_detected.connect(self._on_video_duration_detected)
        self.sp_video_in.valueChanged.connect(self._on_video_in_spin_changed)
        self.sp_video_out.valueChanged.connect(self._on_video_out_spin_changed)

        lay.addWidget(self.grp_video)

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
        # Map widget → (attribuut-naam, waarde-getter). Bij een change-signal
        # gebruiken we sender() om de juiste entry te vinden en passen enkel
        # dat veld toe op alle geselecteerde cues.
        self._field_map: dict = {
            self.ed_number:      ("cue_number",         lambda: self.ed_number.text()),
            self.ed_name:        ("name",               lambda: self.ed_name.text()),
            self.cb_color:       ("color",              lambda: self.cb_color.currentData() or ""),
            self.sp_pre:         ("pre_wait",           lambda: self.sp_pre.value()),
            self.sp_dur:         ("duration",           lambda: self.sp_dur.value()),
            self.sp_post:        ("post_wait",          lambda: self.sp_post.value()),
            self.cb_continue:    ("continue_mode",      lambda: self.cb_continue.currentData()),
            self.ed_path:        ("file_path",          lambda: self.ed_path.text()),
            self.sp_volume:      ("volume_db",          lambda: self.sp_volume.value()),
            self.sp_loops:       ("loops",              lambda: self.sp_loops.value()),
            self.sp_start:       ("audio_start_offset", lambda: self.sp_start.value()),
            self.sp_end:         ("audio_end_offset",   lambda: self.sp_end.value()),
            self.sp_fade_in:     ("audio_fade_in",      lambda: self.sp_fade_in.value()),
            self.sp_fade_out:    ("audio_fade_out",     lambda: self.sp_fade_out.value()),
            self.sp_wait:        ("wait_duration",      lambda: self.sp_wait.value()),
            self.sp_fade_target: ("fade_target_db",     lambda: self.sp_fade_target.value()),
            self.chk_fade_stops: ("fade_stops_target",  lambda: self.chk_fade_stops.isChecked()),
            self.cb_target:      ("target_cue_id",      lambda: self.cb_target.currentData() or ""),
            self.ed_trigger_osc: ("trigger_osc",        lambda: self.ed_trigger_osc.text().strip()),
            self.ed_notes:       ("notes",              lambda: self.ed_notes.toPlainText()),
            self.ed_video_path:   ("file_path",           lambda: self.ed_video_path.text()),
            self.cb_video_screen: ("video_output_screen", lambda: self.cb_video_screen.currentData()),
            self.sp_video_fade_in:  ("video_fade_in",     lambda: self.sp_video_fade_in.value()),
            self.sp_video_fade_out: ("video_fade_out",    lambda: self.sp_video_fade_out.value()),
            self.sp_video_in:       ("video_start_offset", lambda: self.sp_video_in.value()),
            self.sp_video_out:      ("video_end_offset",   lambda: self.sp_video_out.value()),
        }

        for w in (self.ed_number, self.ed_name, self.ed_path, self.ed_notes,
                  self.ed_trigger_osc, self.ed_video_path):
            if isinstance(w, QPlainTextEdit):
                w.textChanged.connect(self._on_any_change)
            else:
                w.textChanged.connect(self._on_any_change)
        for w in (self.sp_pre, self.sp_dur, self.sp_post, self.sp_volume,
                  self.sp_start, self.sp_end, self.sp_fade_in, self.sp_fade_out,
                  self.sp_wait, self.sp_fade_target,
                  self.sp_video_fade_in, self.sp_video_fade_out,
                  self.sp_video_in, self.sp_video_out):
            w.valueChanged.connect(self._on_any_change)
        self.sp_loops.valueChanged.connect(self._on_any_change)
        self.cb_type.currentTextChanged.connect(self._on_type_change)
        self.cb_continue.currentIndexChanged.connect(self._on_any_change)
        self.cb_target.currentIndexChanged.connect(self._on_any_change)
        self.cb_color.currentIndexChanged.connect(self._on_any_change)
        self.cb_video_screen.currentIndexChanged.connect(self._on_any_change)
        self.chk_fade_stops.toggled.connect(self._on_any_change)

        self.set_cues([])

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
        """Back-compat wrapper — roept set_cues aan."""
        self.set_cues([cue] if cue is not None else [])

    def set_cues(self, cues: list[Cue]) -> None:
        self._updating = True
        self.cues = list(cues)
        self.cue = self.cues[0] if self.cues else None

        if not self.cues:
            self.header.setText("Geen cue geselecteerd")
            self.grp_audio.setVisible(False)
            self.grp_video.setVisible(False)
            self.grp_wait.setVisible(False)
            self.grp_target.setVisible(False)
            self.content.setEnabled(False)
            self._updating = False
            return

        self.content.setEnabled(True)
        cue = self.cues[0]
        multi = len(self.cues) > 1

        if multi:
            self.header.setText(f"{len(self.cues)} cues geselecteerd")
        else:
            self.header.setText(f"{cue.cue_number or '?'}: {cue.name or '(naamloos)'}")

        # Toon waarden van de eerste cue — bulk-edits van andere velden
        # overschrijven alleen het gewijzigde veld, niet de rest.
        self.ed_number.setText(cue.cue_number if not multi else "")
        self.ed_name.setText(cue.name if not multi else "")
        self.cb_type.setCurrentText(cue.cue_type)
        self._select_color(cue.color)

        self.sp_pre.setValue(cue.pre_wait)
        self.sp_dur.setValue(cue.duration)
        self.sp_post.setValue(cue.post_wait)
        idx = self.cb_continue.findData(cue.continue_mode)
        if idx >= 0:
            self.cb_continue.setCurrentIndex(idx)

        self.ed_path.setText(cue.file_path if not multi else "")
        self.sp_volume.setValue(cue.volume_db)
        self.sp_loops.setValue(cue.loops)
        self.sp_start.setValue(cue.audio_start_offset)
        self.sp_end.setValue(cue.audio_end_offset)
        self.sp_fade_in.setValue(cue.audio_fade_in)
        self.sp_fade_out.setValue(cue.audio_fade_out)
        self.sp_wait.setValue(cue.wait_duration)
        self.sp_fade_target.setValue(cue.fade_target_db)
        self.chk_fade_stops.setChecked(cue.fade_stops_target)
        self.ed_trigger_osc.setText(cue.trigger_osc if not multi else "")
        self.ed_notes.setPlainText(cue.notes if not multi else "")

        # Video-velden
        self.ed_video_path.setText(cue.file_path if not multi else "")
        idx_screen = self.cb_video_screen.findData(cue.video_output_screen)
        if idx_screen >= 0:
            self.cb_video_screen.setCurrentIndex(idx_screen)
        self.sp_video_fade_in.setValue(cue.video_fade_in)
        self.sp_video_fade_out.setValue(cue.video_fade_out)
        self.sp_video_in.setValue(cue.video_start_offset)
        self.sp_video_out.setValue(cue.video_end_offset)

        # Thumbnail-preview alleen laden voor single-select VIDEO-cues.
        if not multi and cue.cue_type == CueType.VIDEO and cue.file_path:
            self.video_preview.load(
                cue.file_path, cue.video_start_offset, cue.video_end_offset,
            )
        else:
            self.video_preview.load("", 0.0, 0.0)

        self.refresh_targets()
        idx = self.cb_target.findData(cue.target_cue_id)
        if idx >= 0:
            self.cb_target.setCurrentIndex(idx)

        self._update_visibility(cue.cue_type)

        # Per-cue velden uitschakelen bij multi-select.
        for w in (self.ed_number, self.ed_name, self.ed_path, self.ed_notes,
                  self.ed_trigger_osc, self.cb_target, self.btn_browse,
                  self.btn_learn_osc, self.ed_video_path, self.btn_browse_video):
            w.setEnabled(not multi)

        self._updating = False

    def _update_visibility(self, cue_type: str) -> None:
        self.grp_audio.setVisible(cue_type == CueType.AUDIO)
        self.grp_video.setVisible(cue_type == CueType.VIDEO)
        self.grp_wait.setVisible(cue_type == CueType.WAIT)
        self.grp_target.setVisible(cue_type in (CueType.STOP, CueType.FADE, CueType.START))

    # ---- events ------------------------------------------------------------

    def _on_type_change(self, new_type: str) -> None:
        self._update_visibility(new_type)
        if self._updating or not self.cues:
            return
        for c in self.cues:
            c.cue_type = new_type
        self.workspace.dirty = True
        self.cue_changed.emit(self.cues[0])

    def _on_any_change(self) -> None:
        if self._updating or not self.cues:
            return
        sender = self.sender()
        entry = self._field_map.get(sender)
        if entry is None:
            return
        attr, getter = entry
        value = getter()
        # Per-cue velden: alleen op de eerste (bij single-select = de enige).
        targets = self.cues[:1] if attr in self._PER_CUE_ATTRS else self.cues
        for c in targets:
            setattr(c, attr, value)
        self.workspace.dirty = True
        self.cue_changed.emit(self.cues[0])

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

    def _on_video_duration_detected(self, seconds: float) -> None:
        """Preview ontdekte de file-duur; cache 'm op de cue zodat de cuelist
        de 'Duur'-kolom correct kan tonen ook als video_end_offset = 0.
        Bewust géén workspace.dirty — dit is een metadata-cache, geen edit."""
        if self.cue is None or self.cue.cue_type != CueType.VIDEO:
            return
        if abs(self.cue.video_file_duration - seconds) < 0.01:
            return  # al gecached
        self.cue.video_file_duration = seconds
        # Signaal naar mainwindow voor cuelist-refresh, maar workspace blijft schoon.
        self.cue_changed.emit(self.cue)

    def _set_video_in_from_timeline(self, seconds: float) -> None:
        self.sp_video_in.blockSignals(True)
        self.sp_video_in.setValue(seconds)
        self.sp_video_in.blockSignals(False)
        if not self._updating and self.cues:
            for c in self.cues[:1]:  # file_path-samenhangend → per-cue veld
                c.video_start_offset = seconds
            self.workspace.dirty = True
            self.cue_changed.emit(self.cues[0])

    def _set_video_out_from_timeline(self, seconds: float) -> None:
        self.sp_video_out.blockSignals(True)
        self.sp_video_out.setValue(seconds)
        self.sp_video_out.blockSignals(False)
        if not self._updating and self.cues:
            for c in self.cues[:1]:
                c.video_end_offset = seconds
            self.workspace.dirty = True
            self.cue_changed.emit(self.cues[0])

    def _on_video_in_spin_changed(self, v: float) -> None:
        """Spinbox bewoog het in-punt — sync timeline én scrub preview naar
        dat frame zodat je ziet waar je begint."""
        out = self.sp_video_out.value() or self.video_preview.timeline.out_point()
        self.video_preview.set_markers(v, out)
        self.video_preview.scrub_to(v)

    def _on_video_out_spin_changed(self, v: float) -> None:
        """Spinbox bewoog het uit-punt — scrub naar dat frame. v=0 betekent
        'tot einde', dan scrubben we naar de totale duur."""
        in_ = self.sp_video_in.value()
        tl_out = self.video_preview.timeline.out_point()
        visual_out = v if v > 0 else tl_out
        self.video_preview.set_markers(in_, v)
        self.video_preview.scrub_to(visual_out)

    def _browse_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Kies video-bestand", "",
            "Video (*.mp4 *.mov *.avi *.mkv *.webm *.m4v);;Alle bestanden (*)",
        )
        if path:
            # Zelfde auto-fill-naam logica als _browse_file, maar voor video.
            old_path = self.ed_video_path.text().strip()
            name = self.ed_name.text().strip()
            auto_default = bool(re.match(
                r"^(?:" + "|".join(CueType.ALL) + r") \d+$", name
            ))
            from_old_file = bool(old_path) and name == Path(old_path).stem
            should_fill = not name or auto_default or from_old_file

            self.ed_video_path.setText(path)
            if should_fill and self.cue is not None and not len(self.cues) > 1:
                self.ed_name.setText(Path(path).stem)

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
