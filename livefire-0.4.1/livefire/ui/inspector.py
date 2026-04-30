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

from ..cues import Cue, CueType, ContinueMode, PresentationAction
from ..i18n import t
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
        # Presentatie-actie en slide-nummer zijn per cue logisch (bulk-edit
        # naar bv. "Volgende slide" zou álle cues onderling vervangen).
        "presentation_action", "presentation_slide",
        # Network-address/-args is per cue (verschillende OSC-paths per cue).
        # Host en port zijn vaak gelijk over cues heen — laat die bulk-editable.
        "network_address", "network_args",
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

        # Pro-licentie banner — verborgen als het cue-type gratis is of de
        # gebruiker een Pro-licentie heeft. Anders toont 'm een waarschuwing
        # boven het formulier en blijven inputs gewoon werkbaar (je mag
        # bouwen, alleen GO is geblokkeerd).
        from .. import licensing as _lic
        self.banner_pro = QLabel()
        self.banner_pro.setWordWrap(True)
        self.banner_pro.setStyleSheet(
            "background-color: #4d3a1f;"
            "color: #ffd27a;"
            "padding: 8px;"
            "border: 1px solid #806033;"
            "border-radius: 4px;"
        )
        self.banner_pro.setText(
            "🔒 Dit cue-type vereist een Pro-licentie om bij GO af te "
            "spelen. Bouwen mag wel — open Help → Licentie… om te "
            "activeren of een licentie aan te schaffen."
        )
        self.banner_pro.setVisible(False)
        lay.addWidget(self.banner_pro)
        # Refresh banner ook wanneer de licentie elders wordt gewijzigd
        # (bv. via Help → Licentie…). Connectie naar de module-level signaler.
        _lic.signaler.license_changed.connect(self._refresh_pro_banner)

        # ---- Basis-groep ---------------------------------------------------
        grp_basic = QGroupBox(t("group.general"))
        form = QFormLayout(grp_basic)
        self.ed_number = QLineEdit()
        self.ed_number.setToolTip("Cue-nummer zoals getoond in de cuelist. Vrij tekstveld (mag letters bevatten).")
        self.ed_name = QLineEdit()
        self.ed_name.setToolTip("Korte beschrijving voor jezelf. Heeft geen invloed op playback.")
        self.cb_type = QComboBox()
        # Toon vertaalde labels, maar bewaar de originele cue-type-string als
        # data zodat workspaces compatibel blijven.
        for ct in CueType.ALL:
            self.cb_type.addItem(t(f"cuetype.{ct}"), ct)
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
        grp_timing = QGroupBox(t("group.timing"))
        fl = QFormLayout(grp_timing)
        self.sp_pre = self._spin_seconds()
        self.sp_pre.setToolTip("Wachttijd tussen GO en het daadwerkelijk starten van deze cue.")
        self.sp_dur = self._spin_seconds(max_val=36000.0)
        self.sp_dur.setToolTip("Hoe lang de actie duurt. Voor Audio: 0 = speel tot het bestand op is.")
        self.sp_post = self._spin_seconds()
        self.sp_post.setToolTip("Wachttijd nadat de actie klaar is, vóór de cue 'finished' wordt.")
        self.cb_continue = QComboBox()
        for k in ContinueMode.KEYS:
            self.cb_continue.addItem(ContinueMode.label(k), k)
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
        self.grp_audio = QGroupBox(t("group.audio"))
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
        self.grp_video = QGroupBox(t("group.video"))
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
        # Volume voor de audio-track van de video. Range −96..0 dB; libVLC's
        # audio_set_volume kapt boost boven 100% in de meeste builds, dus
        # we tonen geen + waarden.
        self.sp_video_volume = self._spin(-96.0, 0.0, 0.1, " dB")
        self.sp_video_volume.setToolTip(
            "Afspeelvolume van de video-audio in dB. 0 dB = origineel, −6 dB = halve amplitude."
        )
        vl.addRow("Volume", self.sp_video_volume)
        # Wat blijft er fullscreen staan na deze cue tot een volgende start?
        # Standaard zwart; aangevinkt = laatste frame zichtbaar (paused).
        self.chk_video_last_frame = QCheckBox("Bewaar laatste frame na einde")
        self.chk_video_last_frame.setToolTip(
            "Aan: na het einde van deze cue blijft het laatste frame fullscreen "
            "staan tot een volgende cue start.\n"
            "Uit (default): zwart fullscreen tussen cues — geen UI-flits."
        )
        vl.addRow("", self.chk_video_last_frame)

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

        # ---- Image ---------------------------------------------------------
        # Voor losse afbeeldingen én voor slides die uit een PPT zijn
        # geëxporteerd (zie PptImportDialog → MODE_SLIDES).
        self.grp_image = QGroupBox(t("group.image"))
        il = QFormLayout(self.grp_image)
        image_path_row = QHBoxLayout()
        self.ed_image_path = QLineEdit()
        self.ed_image_path.setToolTip("Pad naar het afbeeldingsbestand (PNG/JPG/...).")
        self.btn_browse_image = QPushButton("Bladeren…")
        self.btn_browse_image.setToolTip("Kies een afbeelding.")
        self.btn_browse_image.clicked.connect(self._browse_image)
        image_path_row.addWidget(self.ed_image_path)
        image_path_row.addWidget(self.btn_browse_image)
        ipc = QWidget()
        ipc.setLayout(image_path_row)
        il.addRow("Bestand", ipc)
        self.cb_image_screen = QComboBox()
        self.cb_image_screen.setToolTip(
            "Monitor waarop deze afbeelding fullscreen wordt weergegeven."
        )
        for idx, label in list_screens():
            self.cb_image_screen.addItem(label, idx)
        il.addRow("Output-scherm", self.cb_image_screen)
        self.sp_image_fade_in = self._spin_seconds(max_val=600.0)
        self.sp_image_fade_in.setToolTip("Fade-in vanuit zwart.")
        self.sp_image_fade_out = self._spin_seconds(max_val=600.0)
        self.sp_image_fade_out.setToolTip(
            "Fade-out aan het einde. Alleen relevant als Duur > 0; bij Duur "
            "= 0 blijft de afbeelding staan tot een volgende image-cue op "
            "hetzelfde scherm hem vervangt of een Stop-cue 'm afsluit."
        )
        il.addRow("Fade-in (s)", self.sp_image_fade_in)
        il.addRow("Fade-out (s)", self.sp_image_fade_out)
        lay.addWidget(self.grp_image)

        # ---- Presentation --------------------------------------------------
        self.grp_presentation = QGroupBox(t("group.presentation"))
        ppl = QFormLayout(self.grp_presentation)
        self.cb_ppt_action = QComboBox()
        for key in PresentationAction.ALL:
            self.cb_ppt_action.addItem(PresentationAction.LABELS[key], key)
        self.cb_ppt_action.setToolTip(
            "Welke actie deze cue uitvoert op PowerPoint. 'Open' laadt het\n"
            "bestand en start de slideshow; verdere cues sturen Volgende /\n"
            "Vorige / Goto / Sluit naar de actieve presentatie."
        )
        ppl.addRow("Actie", self.cb_ppt_action)

        ppt_path_row = QHBoxLayout()
        self.ed_ppt_path = QLineEdit()
        self.ed_ppt_path.setToolTip("Pad naar het .pptx-bestand (alleen voor 'Open').")
        self.btn_browse_ppt = QPushButton("Bladeren…")
        self.btn_browse_ppt.clicked.connect(self._browse_ppt)
        ppt_path_row.addWidget(self.ed_ppt_path)
        ppt_path_row.addWidget(self.btn_browse_ppt)
        ppt_path_container = QWidget()
        ppt_path_container.setLayout(ppt_path_row)
        ppl.addRow("Bestand", ppt_path_container)
        self._ppt_path_row = ppt_path_container  # voor show/hide

        self.sp_ppt_slide = QSpinBox()
        self.sp_ppt_slide.setRange(1, 9999)
        self.sp_ppt_slide.setToolTip("Doel-slide (alleen voor 'Ga naar slide').")
        ppl.addRow("Slide-nummer", self.sp_ppt_slide)
        self._ppt_form = ppl

        lay.addWidget(self.grp_presentation)

        # ---- Network (OSC-out) -------------------------------------------
        self.grp_network = QGroupBox(t("group.network"))
        nl = QFormLayout(self.grp_network)
        self.ed_net_address = QLineEdit()
        self.ed_net_address.setPlaceholderText("/companion/page/1/button/1")
        self.ed_net_address.setToolTip(
            "OSC-address. Moet met / beginnen.\n"
            "Companion: /companion/page/<P>/button/<B>\n"
            "QLab:      /cue/<nr>/start"
        )
        nl.addRow("Address", self.ed_net_address)

        host_port_row = QHBoxLayout()
        self.ed_net_host = QLineEdit()
        self.ed_net_host.setPlaceholderText("127.0.0.1")
        self.ed_net_host.setToolTip(
            "Hostnaam of IP-adres van de ontvanger."
        )
        self.sp_net_port = QSpinBox()
        self.sp_net_port.setRange(1, 65535)
        self.sp_net_port.setValue(53000)
        self.sp_net_port.setToolTip(
            "UDP-poort van de ontvanger.\n"
            "Companion: 12321 (default)\n"
            "QLab:      53000 (default)"
        )
        host_port_row.addWidget(self.ed_net_host, 3)
        host_port_row.addWidget(QLabel("Port:"))
        host_port_row.addWidget(self.sp_net_port, 1)
        hpw = QWidget()
        hpw.setLayout(host_port_row)
        nl.addRow("Host", hpw)

        self.ed_net_args = QLineEdit()
        self.ed_net_args.setPlaceholderText("1, 0.5, \"hello world\"")
        self.ed_net_args.setToolTip(
            "OSC-arguments, comma-gescheiden.\n"
            "Token-types: int → float → string (in die volgorde).\n"
            "Quote met \" of ' om strings met spaties of komma's te bewaren.\n"
            "Voorbeelden:\n"
            "  channel, 1, 0.5\n"
            "  \"hello world\", 42\n"
            "Leeg = address zonder args."
        )
        nl.addRow("Args", self.ed_net_args)

        self.btn_net_send = QPushButton(t("btn.test_send"))
        self.btn_net_send.setToolTip(
            "Verstuur dit OSC-bericht direct naar de host:port "
            "zonder de cue te draaien — handig voor het instellen "
            "van Companion-knoppen of QLab-cues."
        )
        self.btn_net_send.clicked.connect(self._test_send_osc)
        net_btn_row = QHBoxLayout()
        net_btn_row.addStretch(1)
        net_btn_row.addWidget(self.btn_net_send)
        nbw = QWidget()
        nbw.setLayout(net_btn_row)
        nl.addRow("", nbw)

        lay.addWidget(self.grp_network)

        # ---- Wait ----------------------------------------------------------
        self.grp_wait = QGroupBox(t("group.wait"))
        wl = QFormLayout(self.grp_wait)
        self.sp_wait = self._spin_seconds(max_val=3600.0)
        self.sp_wait.setToolTip("Hoe lang deze Wait-cue pauzeert voor de playback doorgaat.")
        wl.addRow("Wacht-duur (s)", self.sp_wait)
        lay.addWidget(self.grp_wait)

        # ---- Target (Stop / Fade / Start) ---------------------------------
        self.grp_target = QGroupBox(t("group.target"))
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
        self.grp_triggers = QGroupBox(t("group.triggers"))
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
        grp_notes = QGroupBox(t("group.notes"))
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
            # Hergebruik volume_db: audio en video delen hetzelfde veld zodat
            # je één range hebt om over na te denken (workspace blijft compat).
            self.sp_video_volume:   ("volume_db",           lambda: self.sp_video_volume.value()),
            self.chk_video_last_frame: ("video_last_frame_store", lambda: self.chk_video_last_frame.isChecked()),
            # Image
            self.ed_image_path:        ("file_path",            lambda: self.ed_image_path.text()),
            self.cb_image_screen:      ("image_output_screen",  lambda: self.cb_image_screen.currentData()),
            self.sp_image_fade_in:     ("image_fade_in",        lambda: self.sp_image_fade_in.value()),
            self.sp_image_fade_out:    ("image_fade_out",       lambda: self.sp_image_fade_out.value()),
            # Presentation
            self.cb_ppt_action:     ("presentation_action", lambda: self.cb_ppt_action.currentData()),
            self.ed_ppt_path:       ("file_path",           lambda: self.ed_ppt_path.text()),
            self.sp_ppt_slide:      ("presentation_slide",  lambda: self.sp_ppt_slide.value()),
            # Network (OSC-out)
            self.ed_net_address:    ("network_address",     lambda: self.ed_net_address.text()),
            self.ed_net_host:       ("network_host",        lambda: self.ed_net_host.text()),
            self.sp_net_port:       ("network_port",        lambda: self.sp_net_port.value()),
            self.ed_net_args:       ("network_args",        lambda: self.ed_net_args.text()),
        }

        for w in (self.ed_number, self.ed_name, self.ed_path, self.ed_notes,
                  self.ed_trigger_osc, self.ed_video_path, self.ed_ppt_path,
                  self.ed_image_path,
                  self.ed_net_address, self.ed_net_host, self.ed_net_args):
            if isinstance(w, QPlainTextEdit):
                w.textChanged.connect(self._on_any_change)
            else:
                w.textChanged.connect(self._on_any_change)
        for w in (self.sp_pre, self.sp_dur, self.sp_post, self.sp_volume,
                  self.sp_start, self.sp_end, self.sp_fade_in, self.sp_fade_out,
                  self.sp_wait, self.sp_fade_target,
                  self.sp_video_fade_in, self.sp_video_fade_out,
                  self.sp_video_in, self.sp_video_out,
                  self.sp_video_volume, self.sp_ppt_slide,
                  self.sp_image_fade_in, self.sp_image_fade_out,
                  self.sp_net_port):
            w.valueChanged.connect(self._on_any_change)
        self.sp_loops.valueChanged.connect(self._on_any_change)
        self.cb_type.currentIndexChanged.connect(self._on_type_change)
        self.cb_continue.currentIndexChanged.connect(self._on_any_change)
        self.cb_target.currentIndexChanged.connect(self._on_any_change)
        self.cb_color.currentIndexChanged.connect(self._on_any_change)
        self.cb_video_screen.currentIndexChanged.connect(self._on_any_change)
        self.cb_image_screen.currentIndexChanged.connect(self._on_any_change)
        self.cb_ppt_action.currentIndexChanged.connect(self._on_any_change)
        self.cb_ppt_action.currentIndexChanged.connect(self._update_ppt_visibility)
        self.chk_fade_stops.toggled.connect(self._on_any_change)
        self.chk_video_last_frame.toggled.connect(self._on_any_change)

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
            self.banner_pro.setVisible(False)
            self.grp_audio.setVisible(False)
            self.grp_video.setVisible(False)
            self.grp_image.setVisible(False)
            self.grp_presentation.setVisible(False)
            self.grp_network.setVisible(False)
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
        idx_type = self.cb_type.findData(cue.cue_type)
        if idx_type >= 0:
            self.cb_type.setCurrentIndex(idx_type)
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
        # Volume_db is gedeeld met audio; clamp visueel tot 0 dB voor video
        # zodat de spinbox-waarde binnen de zichtbare range valt.
        self.sp_video_volume.setValue(min(0.0, cue.volume_db))
        self.chk_video_last_frame.setChecked(cue.video_last_frame_store)

        # Image-velden
        self.ed_image_path.setText(cue.file_path if not multi else "")
        idx_iscreen = self.cb_image_screen.findData(cue.image_output_screen)
        if idx_iscreen >= 0:
            self.cb_image_screen.setCurrentIndex(idx_iscreen)
        self.sp_image_fade_in.setValue(cue.image_fade_in)
        self.sp_image_fade_out.setValue(cue.image_fade_out)

        # Presentation-velden
        idx_action = self.cb_ppt_action.findData(cue.presentation_action)
        if idx_action >= 0:
            self.cb_ppt_action.setCurrentIndex(idx_action)
        self.ed_ppt_path.setText(cue.file_path if not multi else "")
        self.sp_ppt_slide.setValue(max(1, cue.presentation_slide))

        # Network-velden (OSC-out)
        self.ed_net_address.setText(cue.network_address if not multi else "")
        self.ed_net_host.setText(cue.network_host)
        self.sp_net_port.setValue(cue.network_port if cue.network_port > 0 else 53000)
        self.ed_net_args.setText(cue.network_args if not multi else "")

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
                  self.btn_learn_osc, self.ed_video_path, self.btn_browse_video,
                  self.ed_ppt_path, self.btn_browse_ppt, self.cb_ppt_action,
                  self.sp_ppt_slide,
                  self.ed_image_path, self.btn_browse_image,
                  self.ed_net_address, self.ed_net_args, self.btn_net_send):
            w.setEnabled(not multi)

        self._updating = False

    def _update_visibility(self, cue_type: str) -> None:
        self.grp_audio.setVisible(cue_type == CueType.AUDIO)
        self.grp_video.setVisible(cue_type == CueType.VIDEO)
        self.grp_image.setVisible(cue_type == CueType.IMAGE)
        self.grp_presentation.setVisible(cue_type == CueType.PRESENTATION)
        self.grp_network.setVisible(cue_type == CueType.NETWORK)
        self.grp_wait.setVisible(cue_type == CueType.WAIT)
        self.grp_target.setVisible(cue_type in (CueType.STOP, CueType.FADE, CueType.START))
        self._update_ppt_visibility()
        self._refresh_pro_banner()

    def _refresh_pro_banner(self) -> None:
        """Toon de licentie-banner als de geselecteerde cue een Pro-type is
        en er geen actieve Pro-licentie is. Roept zich opnieuw aan op een
        license_changed-signal."""
        from .. import licensing as _lic
        if not self.cue:
            self.banner_pro.setVisible(False)
            return
        needs_pro = self.cue.cue_type in _lic.PAID_CUE_TYPES
        self.banner_pro.setVisible(needs_pro and not _lic.is_pro())

    def _update_ppt_visibility(self) -> None:
        """Toon alleen de velden die relevant zijn voor de gekozen
        Presentation-actie (Bestand bij Open, Slide-nummer bij Goto)."""
        action = self.cb_ppt_action.currentData()
        # QFormLayout.setRowVisible werkt op (label, field) paren via row-index.
        self._ppt_form.setRowVisible(self._ppt_path_row,
                                     action == PresentationAction.OPEN)
        self._ppt_form.setRowVisible(self.sp_ppt_slide,
                                     action == PresentationAction.GOTO)

    # ---- events ------------------------------------------------------------

    def _on_type_change(self, _idx: int = 0) -> None:
        new_type = self.cb_type.currentData() or CueType.AUDIO
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
        # Audio file_path-wijziging → preload het nieuwe bestand alvast
        # zodat de eerste GO geen disk-IO doet. Alleen voor audio-cues
        # (de andere file_path-velden hebben hun eigen engine).
        if (attr == "file_path" and self.cues
                and self.cues[0].cue_type == CueType.AUDIO
                and value):
            engine = getattr(self, "audio_engine", None)
            if engine is not None and getattr(engine, "available", False):
                engine.preload_async(value)
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

    def _browse_ppt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Kies presentatie", "",
            "PowerPoint (*.pptx *.ppt *.pptm);;Alle bestanden (*)",
        )
        if not path:
            return
        old_path = self.ed_ppt_path.text().strip()
        name = self.ed_name.text().strip()
        auto_default = bool(re.match(
            r"^(?:" + "|".join(CueType.ALL) + r") \d+$", name
        ))
        from_old_file = bool(old_path) and name == Path(old_path).stem
        should_fill = not name or auto_default or from_old_file
        self.ed_ppt_path.setText(path)
        if should_fill and self.cue is not None and not len(self.cues) > 1:
            self.ed_name.setText(Path(path).stem)

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

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Kies afbeelding", "",
            "Afbeeldingen (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp);;Alle bestanden (*)",
        )
        if not path:
            return
        old_path = self.ed_image_path.text().strip()
        name = self.ed_name.text().strip()
        auto_default = bool(re.match(
            r"^(?:" + "|".join(CueType.ALL) + r") \d+$", name
        ))
        from_old_file = bool(old_path) and name == Path(old_path).stem
        should_fill = not name or auto_default or from_old_file
        self.ed_image_path.setText(path)
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

    # Door MainWindow gezet: inspector.osc_out_engine = controller.osc_out
    osc_out_engine = None

    # Door MainWindow gezet: inspector.audio_engine = controller.audio
    # Gebruikt om bij een file_path-edit op een audio-cue alvast te
    # preloaden (geen disk-IO bij GO).
    audio_engine = None

    def _test_send_osc(self) -> None:
        """Verstuur het OSC-bericht uit de Network-groep direct, zonder
        de cue te hoeven afspelen — handig voor het inrichten van
        Companion-knoppen of QLab-cues."""
        from PyQt6.QtWidgets import QMessageBox
        from ..engines.osc_out import parse_args
        if self.osc_out_engine is None:
            QMessageBox.warning(
                self, "OSC-output niet beschikbaar",
                "De OSC-output engine is niet aangesloten.",
            )
            return
        addr = self.ed_net_address.text().strip()
        host = self.ed_net_host.text().strip() or "127.0.0.1"
        port = self.sp_net_port.value()
        args = parse_args(self.ed_net_args.text())
        ok, err = self.osc_out_engine.send(host, port, addr, args)
        if not ok:
            QMessageBox.warning(self, "OSC-versturen mislukt", err)
            return
        # Compacte bevestiging in de statusbar van het hoofdvenster zou
        # mooi zijn; voor nu een korte tooltip-flash op de knop.
        self.btn_net_send.setText(t("btn.test_send.done"))
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(
            1200, lambda: self.btn_net_send.setText(t("btn.test_send"))
        )

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
