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
    QCheckBox, QHBoxLayout, QLabel, QToolButton, QButtonGroup,
)

from ..cues import Cue, CueType, ContinueMode, PresentationAction
from ..i18n import t
from ..engines.video import list_screens
from ..workspace import Workspace
from .style import CUE_COLORS, TEXT_DIM
from .video_preview import VideoPreviewWidget


def _swatch_icon(hex_color: str, size: int = 14) -> QIcon:
    """Maak een vierkant kleur-swatch als QIcon (bv. voor menus of icons)."""
    pm = QPixmap(size, size)
    if hex_color:
        pm.fill(QColor(hex_color))
    else:
        pm.fill(QColor(0, 0, 0, 0))  # transparant voor "None"
    return QIcon(pm)


class _ColorSwatchPicker(QWidget):
    """Rij kleine klikbare kleurvierkantjes — vervangt een dropdown waar
    enkel een kleur uit een vaste palette gekozen wordt. De swatches
    staan naast elkaar; de actieve swatch krijgt een witte ring zodat
    ie er meteen uitspringt op een donker thema.

    Eerste swatch is altijd "None" (lege hex), zichtbaar gemaakt met een
    diagonale streep zodat het verschil met écht zwart duidelijk blijft.

    API:
      ``current_color()``  → hex-string (lege string = geen kleur)
      ``set_current(hex)`` → selecteer voor display
      ``color_changed``    → pyqtSignal(str), fired bij user-klik
    """

    color_changed = pyqtSignal(str)

    _SWATCH_SIZE = 18

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current: str = ""
        self._buttons: dict[str, QToolButton] = {}
        # autoExclusive op losse buttons werkt niet zonder QButtonGroup
        # — anders blijven meerdere checked als je rondklikt.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        for label, hex_color in CUE_COLORS:
            btn = QToolButton(self)
            btn.setCheckable(True)
            btn.setFixedSize(self._SWATCH_SIZE, self._SWATCH_SIZE)
            btn.setToolTip(label)
            btn.setStyleSheet(self._stylesheet_for(hex_color, checked=False))
            btn.clicked.connect(
                lambda _checked, hc=hex_color: self._on_pick(hc)
            )
            self._group.addButton(btn)
            self._buttons[hex_color] = btn
            lay.addWidget(btn)

        lay.addStretch(1)

    # ---- public API --------------------------------------------------------

    def current_color(self) -> str:
        return self._current

    def set_current(self, hex_color: str) -> None:
        """Selecteer een kleur zonder color_changed te emitten. Een kleur
        die niet in de standaard-palette zit wordt als losse swatch aan
        het einde toegevoegd (custom-from-workspace fallback)."""
        if hex_color and hex_color not in self._buttons:
            self._add_custom_swatch(hex_color)
        self._current = hex_color
        for hc, btn in self._buttons.items():
            checked = (hc == hex_color)
            btn.setChecked(checked)
            btn.setStyleSheet(self._stylesheet_for(hc, checked=checked))

    # ---- intern ------------------------------------------------------------

    def _on_pick(self, hex_color: str) -> None:
        if hex_color == self._current:
            # Hertekenen voor het geval autoExclusive 't visueel niet
            # gesynchroniseerd heeft.
            self._buttons[hex_color].setStyleSheet(
                self._stylesheet_for(hex_color, checked=True)
            )
            return
        self.set_current(hex_color)
        self.color_changed.emit(hex_color)

    def _add_custom_swatch(self, hex_color: str) -> None:
        """Voeg een onbekende workspace-kleur toe aan het einde van de rij."""
        btn = QToolButton(self)
        btn.setCheckable(True)
        btn.setFixedSize(self._SWATCH_SIZE, self._SWATCH_SIZE)
        btn.setToolTip(f"Custom ({hex_color})")
        btn.setStyleSheet(self._stylesheet_for(hex_color, checked=False))
        btn.clicked.connect(lambda _c, hc=hex_color: self._on_pick(hc))
        self._group.addButton(btn)
        self._buttons[hex_color] = btn
        # Insert vóór de stretch — de stretch hangt aan het einde.
        lay = self.layout()
        lay.insertWidget(lay.count() - 1, btn)

    @staticmethod
    def _stylesheet_for(hex_color: str, *, checked: bool) -> str:
        """Stylesheet per swatch: gevulde achtergrond + ring bij selectie.
        'None' (lege hex) toont een diagonale streep i.p.v. een vlak zwart
        vierkant zodat 't verschil met echt-zwart duidelijk blijft."""
        ring = "border: 2px solid #ffffff;" if checked else "border: 1px solid #555555;"
        if hex_color:
            bg = f"background-color: {hex_color};"
        else:
            # Diagonale streep over een neutrale grijze achtergrond,
            # opgebouwd via een qlineargradient — geen extra image-asset
            # nodig.
            bg = (
                "background: qlineargradient("
                "x1:0, y1:0, x2:1, y2:1, "
                "stop:0 #2a2a2a, stop:0.45 #2a2a2a, "
                "stop:0.46 #d9534f, stop:0.54 #d9534f, "
                "stop:0.55 #2a2a2a, stop:1 #2a2a2a);"
            )
        return f"QToolButton {{ {bg} {ring} border-radius: 3px; }}"


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
        # DMX-values en chase-steps zijn evident per cue (een snapshot is
        # cue-specifiek). Universe / protocol / host / port mogen bulk
        # zodat een hele set DMX-cues in één klap naar een ander rig
        # gerouteerd kan worden.
        "dmx_values", "dmx_chase_steps",
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
        self.header = QLabel("No cue selected")
        f = QFont()
        f.setPointSize(10)  # 1pt boven base (Segoe UI 9pt) — VS-stijl hiërarchie
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
            "🔒 This cue type requires a Pro license to fire on GO. "
            "Building is allowed — open Help → License… to activate or "
            "purchase a license."
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
        self.ed_number.setToolTip("Cue number as shown in the cuelist. Free text field (may contain letters).")
        self.ed_name = QLineEdit()
        self.ed_name.setToolTip("Short description for yourself. Does not affect playback.")
        self.cb_type = QComboBox()
        # Toon vertaalde labels, maar bewaar de originele cue-type-string als
        # data zodat workspaces compatibel blijven.
        for ct in CueType.ALL:
            self.cb_type.addItem(t(f"cuetype.{ct}"), ct)
        self.cb_type.setToolTip(
            "Cue type:\n"
            "• Audio — play a file\n"
            "• Fade — change the volume of another audio cue\n"
            "• Wait — pause for a set duration\n"
            "• Stop — stop a specific cue or everything\n"
            "• Start — trigger another cue\n"
            "• Group — container (placeholder in v0.3)\n"
            "• Memo — note only, no action"
        )
        self.cb_color = _ColorSwatchPicker()
        self.cb_color.setToolTip("Color tag shown as a bar in the cuelist.")
        form.addRow("Number", self.ed_number)
        form.addRow("Type", self.cb_type)
        form.addRow("Name", self.ed_name)
        form.addRow("Color", self.cb_color)
        lay.addWidget(grp_basic)

        # ---- Timing --------------------------------------------------------
        grp_timing = QGroupBox(t("group.timing"))
        fl = QFormLayout(grp_timing)
        self.sp_pre = self._spin_seconds()
        self.sp_pre.setToolTip("Wait time between GO and the actual start of this cue.")
        self.sp_dur = self._spin_seconds(max_val=36000.0)
        self.sp_dur.setToolTip("How long the action lasts. For Audio: 0 = play until the file ends.")
        self.sp_post = self._spin_seconds()
        self.sp_post.setToolTip("Wait time after the action completes, before the cue becomes 'finished'.")
        self.cb_continue = QComboBox()
        for k in ContinueMode.KEYS:
            self.cb_continue.addItem(ContinueMode.label(k), k)
        self.cb_continue.setToolTip(
            "How playback continues:\n"
            "• Do Not Continue — stops after this cue\n"
            "• Auto-Continue — next cue starts as soon as this one starts its action\n"
            "• Auto-Follow — next cue starts after this one is finished"
        )
        fl.addRow("Pre-wait", self.sp_pre)
        fl.addRow("Duration", self.sp_dur)
        fl.addRow("Post-wait", self.sp_post)
        fl.addRow("Continue", self.cb_continue)
        lay.addWidget(grp_timing)

        # ---- Audio ---------------------------------------------------------
        self.grp_audio = QGroupBox(t("group.audio"))
        al = QFormLayout(self.grp_audio)
        path_row = QHBoxLayout()
        self.ed_path = QLineEdit()
        self.ed_path.setToolTip("Path to the audio file (wav/mp3/flac/ogg/aiff).")
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setToolTip("Open a file dialog to choose an audio file.")
        self.btn_browse.clicked.connect(self._browse_file)
        path_row.addWidget(self.ed_path)
        path_row.addWidget(self.btn_browse)
        path_container = QWidget()
        path_container.setLayout(path_row)
        al.addRow("File", path_container)
        self.sp_volume = self._spin(-96.0, 12.0, 0.1, " dB")
        self.sp_volume.setToolTip("Playback volume in dB. 0 dB = original, −6 dB = half amplitude.")
        self.sp_loops = QSpinBox()
        self.sp_loops.setRange(0, 9999)
        self.sp_loops.setSpecialValueText("∞")
        self.sp_loops.setToolTip("How many times to play the file. 0 = loop indefinitely.")
        self.sp_start = self._spin_seconds()
        self.sp_start.setToolTip("Seconds to skip from the beginning of the file.")
        self.sp_end = self._spin_seconds()
        self.sp_end.setToolTip("Seconds to trim from the end of the file.")
        self.sp_fade_in = self._spin_seconds(max_val=600.0)
        self.sp_fade_in.setToolTip("Fade-in time. Cue starts silent and ramps to the set volume.")
        self.sp_fade_out = self._spin_seconds(max_val=600.0)
        self.sp_fade_out.setToolTip(
            "Fade-out time at the end of the cue. With AUTO_FOLLOW the next cue "
            "starts simultaneously with the fade-out — giving a natural crossfade."
        )
        al.addRow("Volume", self.sp_volume)
        al.addRow("Loops (0 = ∞)", self.sp_loops)
        al.addRow("Start offset", self.sp_start)
        al.addRow("End offset", self.sp_end)
        al.addRow("Fade-in", self.sp_fade_in)
        al.addRow("Fade-out", self.sp_fade_out)
        lay.addWidget(self.grp_audio)

        # ---- Video ---------------------------------------------------------
        self.grp_video = QGroupBox(t("group.video"))
        vl = QFormLayout(self.grp_video)
        video_path_row = QHBoxLayout()
        self.ed_video_path = QLineEdit()
        self.ed_video_path.setToolTip("Path to the video file.")
        self.btn_browse_video = QPushButton("Browse…")
        self.btn_browse_video.setToolTip("Choose a video file.")
        self.btn_browse_video.clicked.connect(self._browse_video)
        video_path_row.addWidget(self.ed_video_path)
        video_path_row.addWidget(self.btn_browse_video)
        vpc = QWidget()
        vpc.setLayout(video_path_row)
        vl.addRow("File", vpc)
        self.cb_video_screen = QComboBox()
        self.cb_video_screen.setToolTip(
            "Monitor on which this cue is displayed fullscreen."
        )
        for idx, label in list_screens():
            self.cb_video_screen.addItem(label, idx)
        vl.addRow("Output screen", self.cb_video_screen)
        self.sp_video_fade_in = self._spin_seconds(max_val=600.0)
        self.sp_video_fade_in.setToolTip("Fade in from black.")
        self.sp_video_fade_out = self._spin_seconds(max_val=600.0)
        self.sp_video_fade_out.setToolTip("Fade to black at the end of the cue.")
        vl.addRow("Fade-in", self.sp_video_fade_in)
        vl.addRow("Fade-out", self.sp_video_fade_out)
        # Volume voor de audio-track van de video. Range −96..0 dB; libVLC's
        # audio_set_volume kapt boost boven 100% in de meeste builds, dus
        # we tonen geen + waarden.
        self.sp_video_volume = self._spin(-96.0, 0.0, 0.1, " dB")
        self.sp_video_volume.setToolTip(
            "Playback volume of the video audio in dB. 0 dB = original, −6 dB = half amplitude."
        )
        vl.addRow("Volume", self.sp_video_volume)
        # Wat blijft er fullscreen staan na deze cue tot een volgende start?
        # Standaard zwart; aangevinkt = laatste frame zichtbaar (paused).
        self.chk_video_last_frame = QCheckBox("Keep last frame after end")
        self.chk_video_last_frame.setToolTip(
            "On: after this cue ends, the last frame stays fullscreen until "
            "the next cue starts.\n"
            "Off (default): black fullscreen between cues — no UI flash."
        )
        vl.addRow("", self.chk_video_last_frame)

        # Thumbnail + timeline voor in/uit-punt scrubbing.
        self.video_preview = VideoPreviewWidget()
        vl.addRow(self.video_preview)

        self.sp_video_in = self._spin_seconds(max_val=36000.0)
        self.sp_video_in.setToolTip("In point (the moment from which playback starts).")
        self.sp_video_out = self._spin_seconds(max_val=36000.0)
        self.sp_video_out.setToolTip("Out point (where the cue ends). 0 = play to end of file.")
        vl.addRow("In point", self.sp_video_in)
        vl.addRow("Out point", self.sp_video_out)

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
        self.ed_image_path.setToolTip("Path to the image file (PNG/JPG/...).")
        self.btn_browse_image = QPushButton("Browse…")
        self.btn_browse_image.setToolTip("Choose an image.")
        self.btn_browse_image.clicked.connect(self._browse_image)
        image_path_row.addWidget(self.ed_image_path)
        image_path_row.addWidget(self.btn_browse_image)
        ipc = QWidget()
        ipc.setLayout(image_path_row)
        il.addRow("File", ipc)
        self.cb_image_screen = QComboBox()
        self.cb_image_screen.setToolTip(
            "Monitor on which this image is displayed fullscreen."
        )
        for idx, label in list_screens():
            self.cb_image_screen.addItem(label, idx)
        il.addRow("Output screen", self.cb_image_screen)
        self.sp_image_fade_in = self._spin_seconds(max_val=600.0)
        self.sp_image_fade_in.setToolTip("Fade in from black.")
        self.sp_image_fade_out = self._spin_seconds(max_val=600.0)
        self.sp_image_fade_out.setToolTip(
            "Fade-out at the end. Only relevant if Duration > 0; with "
            "Duration = 0 the image stays until another image cue on the "
            "same screen replaces it or a Stop cue closes it."
        )
        il.addRow("Fade-in", self.sp_image_fade_in)
        il.addRow("Fade-out", self.sp_image_fade_out)
        lay.addWidget(self.grp_image)

        # ---- Presentation --------------------------------------------------
        self.grp_presentation = QGroupBox(t("group.presentation"))
        ppl = QFormLayout(self.grp_presentation)
        self.cb_ppt_action = QComboBox()
        for key in PresentationAction.ALL:
            self.cb_ppt_action.addItem(PresentationAction.LABELS[key], key)
        self.cb_ppt_action.setToolTip(
            "What action this cue performs on PowerPoint. 'Open' loads the\n"
            "file and starts the slideshow; further cues send Next /\n"
            "Previous / Go To / Close to the active presentation."
        )
        ppl.addRow("Action", self.cb_ppt_action)

        ppt_path_row = QHBoxLayout()
        self.ed_ppt_path = QLineEdit()
        self.ed_ppt_path.setToolTip("Path to the .pptx file (only for 'Open').")
        self.btn_browse_ppt = QPushButton("Browse…")
        self.btn_browse_ppt.clicked.connect(self._browse_ppt)
        ppt_path_row.addWidget(self.ed_ppt_path)
        ppt_path_row.addWidget(self.btn_browse_ppt)
        ppt_path_container = QWidget()
        ppt_path_container.setLayout(ppt_path_row)
        ppl.addRow("File", ppt_path_container)
        self._ppt_path_row = ppt_path_container  # voor show/hide

        self.sp_ppt_slide = QSpinBox()
        self.sp_ppt_slide.setRange(1, 9999)
        self.sp_ppt_slide.setToolTip("Target slide (only for 'Go to slide').")
        ppl.addRow("Slide number", self.sp_ppt_slide)
        self._ppt_form = ppl

        lay.addWidget(self.grp_presentation)

        # ---- Network (OSC-out) -------------------------------------------
        self.grp_network = QGroupBox(t("group.network"))
        nl = QFormLayout(self.grp_network)
        self.ed_net_address = QLineEdit()
        self.ed_net_address.setPlaceholderText("/companion/page/1/button/1")
        self.ed_net_address.setToolTip(
            "OSC address. Must start with /.\n"
            "Companion: /companion/page/<P>/button/<B>\n"
            "QLab:      /cue/<nr>/start"
        )
        nl.addRow("Address", self.ed_net_address)

        host_port_row = QHBoxLayout()
        self.ed_net_host = QLineEdit()
        self.ed_net_host.setPlaceholderText("127.0.0.1")
        self.ed_net_host.setToolTip(
            "Hostname or IP address of the receiver."
        )
        self.sp_net_port = QSpinBox()
        self.sp_net_port.setRange(1, 65535)
        self.sp_net_port.setValue(53000)
        self.sp_net_port.setToolTip(
            "UDP port of the receiver.\n"
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
            "OSC arguments, comma-separated.\n"
            "Token types: int → float → string (in that order).\n"
            "Quote with \" or ' to preserve strings with spaces or commas.\n"
            "Examples:\n"
            "  channel, 1, 0.5\n"
            "  \"hello world\", 42\n"
            "Empty = address without args."
        )
        nl.addRow("Args", self.ed_net_args)

        self.btn_net_send = QPushButton(t("btn.test_send"))
        self.btn_net_send.setToolTip(
            "Send this OSC message directly to host:port without running "
            "the cue — useful when configuring Companion buttons or QLab "
            "cues."
        )
        self.btn_net_send.clicked.connect(self._test_send_osc)
        net_btn_row = QHBoxLayout()
        net_btn_row.addStretch(1)
        net_btn_row.addWidget(self.btn_net_send)
        nbw = QWidget()
        nbw.setLayout(net_btn_row)
        nl.addRow("", nbw)

        lay.addWidget(self.grp_network)

        # ---- DMX (Art-Net + sACN, v0.5.0) --------------------------------
        self.grp_dmx = QGroupBox(t("group.dmx"))
        dl = QFormLayout(self.grp_dmx)

        self.cb_dmx_protocol = QComboBox()
        self.cb_dmx_protocol.addItem("Art-Net", "artnet")
        self.cb_dmx_protocol.addItem("sACN (E1.31)", "sacn")
        self.cb_dmx_protocol.setToolTip(
            "Art-Net = UDP unicast/broadcast op port 6454.\n"
            "sACN = E1.31 multicast 239.255.<hi>.<lo> port 5568."
        )
        dl.addRow("Protocol", self.cb_dmx_protocol)

        self.sp_dmx_universe = QSpinBox()
        self.sp_dmx_universe.setRange(0, 32767)
        self.sp_dmx_universe.setToolTip(
            "DMX universe number. Art-Net packs subnet+net+universe in 15 bits; "
            "sACN uses 16-bit universe (typical 1..63999)."
        )
        dl.addRow("Universe", self.sp_dmx_universe)

        dmx_host_row = QHBoxLayout()
        self.ed_dmx_host = QLineEdit()
        self.ed_dmx_host.setPlaceholderText("(broadcast / multicast)")
        self.ed_dmx_host.setToolTip(
            "Target IP. Empty = broadcast (Art-Net) or multicast group "
            "(sACN). Use a unicast IP to address one node."
        )
        self.sp_dmx_port = QSpinBox()
        self.sp_dmx_port.setRange(1, 65535)
        self.sp_dmx_port.setToolTip(
            "UDP port. Art-Net default 6454; sACN default 5568."
        )
        dmx_host_row.addWidget(self.ed_dmx_host, 3)
        dmx_host_row.addWidget(QLabel("Port:"))
        dmx_host_row.addWidget(self.sp_dmx_port, 1)
        dmx_host_container = QWidget()
        dmx_host_container.setLayout(dmx_host_row)
        dl.addRow("Host", dmx_host_container)

        self.cb_dmx_mode = QComboBox()
        self.cb_dmx_mode.addItem("Snapshot", "snapshot")
        self.cb_dmx_mode.addItem("Fade", "fade")
        self.cb_dmx_mode.addItem("Chase", "chase")
        self.cb_dmx_mode.setToolTip(
            "Snapshot — apply values instantly (LTP overrides previous cues).\n"
            "Fade — linear ramp from current to target over Fade time.\n"
            "Chase — cycle through chase steps with the configured step time."
        )
        dl.addRow("Mode", self.cb_dmx_mode)

        self.ed_dmx_values = QPlainTextEdit()
        self.ed_dmx_values.setPlaceholderText("1:255, 17:128, 33:64")
        self.ed_dmx_values.setFixedHeight(56)
        self.ed_dmx_values.setToolTip(
            "DMX values as channel:value pairs, comma-separated. Channels "
            "1..512, values 0..255. Used for snapshot and fade modes."
        )
        dl.addRow("Values", self.ed_dmx_values)

        self.sp_dmx_fade = self._spin_seconds(max_val=600.0)
        self.sp_dmx_fade.setToolTip(
            "Fade duration in seconds. Only applied in Fade mode."
        )
        dl.addRow("Fade time", self.sp_dmx_fade)

        self.ed_dmx_chase = QPlainTextEdit()
        self.ed_dmx_chase.setPlaceholderText("1:255 | 1:0,17:255 | 17:0")
        self.ed_dmx_chase.setFixedHeight(70)
        self.ed_dmx_chase.setToolTip(
            "Chase steps separated by ' | '. Each step is a channel:value "
            "list like in Values. Used in Chase mode."
        )
        dl.addRow("Chase steps", self.ed_dmx_chase)

        self.sp_dmx_step = self._spin_seconds(max_val=600.0)
        self.sp_dmx_step.setToolTip("Time per chase step (seconds).")
        dl.addRow("Step time", self.sp_dmx_step)

        self.sp_dmx_chase_loops = QSpinBox()
        self.sp_dmx_chase_loops.setRange(0, 9999)
        self.sp_dmx_chase_loops.setSpecialValueText("∞")
        self.sp_dmx_chase_loops.setToolTip(
            "How many times to repeat the chase. 0 = loop indefinitely "
            "(stop with a Stop cue)."
        )
        dl.addRow("Chase loops (0 = ∞)", self.sp_dmx_chase_loops)

        self.chk_dmx_pingpong = QCheckBox("Ping-pong chase")
        self.chk_dmx_pingpong.setToolTip(
            "On = chase reverses at the end of each loop "
            "(1→2→3→2→1→2→…). Off = wraps to the first step."
        )
        dl.addRow("", self.chk_dmx_pingpong)

        lay.addWidget(self.grp_dmx)

        # ---- Wait ----------------------------------------------------------
        self.grp_wait = QGroupBox(t("group.wait"))
        wl = QFormLayout(self.grp_wait)
        self.sp_wait = self._spin_seconds(max_val=3600.0)
        self.sp_wait.setToolTip("How long this Wait cue pauses before playback continues.")
        wl.addRow("Wait duration", self.sp_wait)
        lay.addWidget(self.grp_wait)

        # ---- Group --------------------------------------------------------
        self.grp_group = QGroupBox(t("group.group"))
        gl = QFormLayout(self.grp_group)
        self.cb_group_mode = QComboBox()
        self.cb_group_mode.addItem("List — step through manually", "list")
        self.cb_group_mode.addItem("First, then list — auto-chain children", "first-then-list")
        self.cb_group_mode.addItem("Parallel — fire all children at once", "parallel")
        self.cb_group_mode.addItem("Random — fire one random child", "random")
        self.cb_group_mode.setToolTip(
            "How this group behaves when GO'd:\n"
            "• List — playhead enters the group; you GO through children manually\n"
            "• First, then list — fires the first child, then auto-chains the rest\n"
            "• Parallel — fires all children at the same time\n"
            "• Random — fires one randomly picked child"
        )
        gl.addRow("Mode", self.cb_group_mode)
        self.lbl_group_children = QLabel()
        self.lbl_group_children.setStyleSheet(f"color: {TEXT_DIM};")
        gl.addRow("Children", self.lbl_group_children)
        lay.addWidget(self.grp_group)

        # ---- Target (Stop / Fade / Start) ---------------------------------
        self.grp_target = QGroupBox(t("group.target"))
        tl = QFormLayout(self.grp_target)
        self.cb_target = QComboBox()
        self.cb_target.setToolTip(
            "The cue this Stop/Fade/Start acts on. For Stop: empty = stop everything."
        )
        tl.addRow("Target cue", self.cb_target)
        self.sp_fade_target = self._spin(-96.0, 12.0, 0.1, " dB")
        self.sp_fade_target.setToolTip("The volume the Fade targets (for Fade cues).")
        self.chk_fade_stops = QCheckBox("Stop target after fade")
        self.chk_fade_stops.setToolTip(
            "Enable to stop the target cue as soon as the fade-out reaches −∞ dB."
        )
        tl.addRow("Fade to", self.sp_fade_target)
        tl.addRow("", self.chk_fade_stops)
        lay.addWidget(self.grp_target)

        # ---- Triggers ------------------------------------------------------
        self.grp_triggers = QGroupBox(t("group.triggers"))
        trg = QFormLayout(self.grp_triggers)
        osc_row = QHBoxLayout()
        self.ed_trigger_osc = QLineEdit()
        self.ed_trigger_osc.setPlaceholderText("/livefire/go/intro — empty = no trigger")
        self.ed_trigger_osc.setToolTip(
            "OSC address that fires this cue when received on the OSC-input "
            "port (configurable in Preferences). Empty = no external trigger."
        )
        self.btn_learn_osc = QPushButton("Learn…")
        self.btn_learn_osc.setToolTip(
            "Wait for the next OSC message and fill in the address automatically. "
            "OSC input must be enabled."
        )
        self.btn_learn_osc.clicked.connect(self._learn_osc)
        osc_row.addWidget(self.ed_trigger_osc)
        osc_row.addWidget(self.btn_learn_osc)
        osc_container = QWidget()
        osc_container.setLayout(osc_row)
        trg.addRow("OSC address", osc_container)
        lay.addWidget(self.grp_triggers)

        # ---- Notities ------------------------------------------------------
        grp_notes = QGroupBox(t("group.notes"))
        nl = QVBoxLayout(grp_notes)
        self.ed_notes = QPlainTextEdit()
        self.ed_notes.setMinimumHeight(60)
        self.ed_notes.setToolTip("Free notes for yourself. Shown in Memo cues.")
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
            self.cb_color:       ("color",              lambda: self.cb_color.current_color()),
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
            # Group
            self.cb_group_mode:     ("group_mode",          lambda: self.cb_group_mode.currentData()),
            # DMX (Art-Net + sACN)
            self.cb_dmx_protocol:   ("dmx_protocol",        lambda: self.cb_dmx_protocol.currentData()),
            self.sp_dmx_universe:   ("dmx_universe",        lambda: self.sp_dmx_universe.value()),
            self.ed_dmx_host:       ("dmx_host",            lambda: self.ed_dmx_host.text().strip()),
            self.sp_dmx_port:       ("dmx_port",            lambda: self.sp_dmx_port.value()),
            self.cb_dmx_mode:       ("dmx_mode",            lambda: self.cb_dmx_mode.currentData()),
            self.ed_dmx_values:     ("dmx_values",          lambda: self.ed_dmx_values.toPlainText()),
            self.sp_dmx_fade:       ("dmx_fade_time",       lambda: self.sp_dmx_fade.value()),
            self.ed_dmx_chase:      ("dmx_chase_steps",     lambda: self.ed_dmx_chase.toPlainText()),
            self.sp_dmx_step:       ("dmx_step_time",       lambda: self.sp_dmx_step.value()),
            self.sp_dmx_chase_loops:("dmx_chase_loops",     lambda: self.sp_dmx_chase_loops.value()),
            self.chk_dmx_pingpong:  ("dmx_chase_pingpong",  lambda: self.chk_dmx_pingpong.isChecked()),
        }

        for w in (self.ed_number, self.ed_name, self.ed_path, self.ed_notes,
                  self.ed_trigger_osc, self.ed_video_path, self.ed_ppt_path,
                  self.ed_image_path,
                  self.ed_net_address, self.ed_net_host, self.ed_net_args,
                  self.ed_dmx_host,
                  self.ed_dmx_values, self.ed_dmx_chase):
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
                  self.sp_net_port,
                  self.sp_dmx_universe, self.sp_dmx_port, self.sp_dmx_fade,
                  self.sp_dmx_step, self.sp_dmx_chase_loops):
            w.valueChanged.connect(self._on_any_change)
        self.sp_loops.valueChanged.connect(self._on_any_change)
        self.cb_type.currentIndexChanged.connect(self._on_type_change)
        self.cb_continue.currentIndexChanged.connect(self._on_any_change)
        self.cb_target.currentIndexChanged.connect(self._on_any_change)
        self.cb_color.color_changed.connect(self._on_any_change)
        self.cb_video_screen.currentIndexChanged.connect(self._on_any_change)
        self.cb_image_screen.currentIndexChanged.connect(self._on_any_change)
        self.cb_ppt_action.currentIndexChanged.connect(self._on_any_change)
        self.cb_ppt_action.currentIndexChanged.connect(self._update_ppt_visibility)
        self.chk_fade_stops.toggled.connect(self._on_any_change)
        self.chk_video_last_frame.toggled.connect(self._on_any_change)
        self.cb_group_mode.currentIndexChanged.connect(self._on_any_change)
        self.cb_dmx_protocol.currentIndexChanged.connect(self._on_any_change)
        self.cb_dmx_protocol.currentIndexChanged.connect(self._on_dmx_protocol_change)
        self.cb_dmx_mode.currentIndexChanged.connect(self._on_any_change)
        self.cb_dmx_mode.currentIndexChanged.connect(self._update_dmx_visibility)
        self.chk_dmx_pingpong.toggled.connect(self._on_any_change)

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
        self.cb_target.addItem("— all / none —", "")
        for c in self.workspace.cues:
            label = f"{c.cue_number or '?'}: {c.name or '(untitled)'} [{c.cue_type}]"
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

    def set_readonly(self, on: bool) -> None:
        """Disable alle interactieve form-velden tijdens showtime-lock.
        scroll_area + headers blijven enabled zodat de operator nog wel
        kan kijken. _destructive_blocked() vangt eventuele muterende
        paden alsnog af; deze method zorgt voor de UI-state-feedback."""
        # Iterate over alle child-widgets die input accepteren — netter
        # dan elke spinbox/combo/edit hier handmatig op te sommen.
        for child in self.findChildren(QWidget):
            if isinstance(child, (
                QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
                QPlainTextEdit, QPushButton,
            )):
                # Save-as / Browse-knoppen op de Pro-banner laten we wel
                # enabled (geen workspace-mutatie). Maar push-knoppen op
                # cue-velden (Browse, Test verzenden, Learn) gaan uit.
                child.setEnabled(not on)

    def set_cues(self, cues: list[Cue]) -> None:
        self._updating = True
        self.cues = list(cues)
        self.cue = self.cues[0] if self.cues else None

        if not self.cues:
            self.header.setText("No cue selected")
            self.banner_pro.setVisible(False)
            self.grp_audio.setVisible(False)
            self.grp_video.setVisible(False)
            self.grp_image.setVisible(False)
            self.grp_presentation.setVisible(False)
            self.grp_network.setVisible(False)
            self.grp_dmx.setVisible(False)
            self.grp_wait.setVisible(False)
            self.grp_group.setVisible(False)
            self.grp_target.setVisible(False)
            self.content.setEnabled(False)
            self._updating = False
            return

        self.content.setEnabled(True)
        cue = self.cues[0]
        multi = len(self.cues) > 1

        if multi:
            self.header.setText(f"{len(self.cues)} cues selected")
        else:
            self.header.setText(f"{cue.cue_number or '?'}: {cue.name or '(untitled)'}")

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

        # DMX-velden
        idx_proto = self.cb_dmx_protocol.findData(cue.dmx_protocol or "artnet")
        if idx_proto >= 0:
            self.cb_dmx_protocol.setCurrentIndex(idx_proto)
        self.sp_dmx_universe.setValue(int(cue.dmx_universe))
        self.ed_dmx_host.setText(cue.dmx_host)
        self.sp_dmx_port.setValue(
            cue.dmx_port if cue.dmx_port > 0 else (
                6454 if (cue.dmx_protocol or "artnet") == "artnet" else 5568
            )
        )
        idx_mode = self.cb_dmx_mode.findData(cue.dmx_mode or "snapshot")
        if idx_mode >= 0:
            self.cb_dmx_mode.setCurrentIndex(idx_mode)
        self.ed_dmx_values.setPlainText(cue.dmx_values if not multi else "")
        self.sp_dmx_fade.setValue(float(cue.dmx_fade_time))
        self.ed_dmx_chase.setPlainText(cue.dmx_chase_steps if not multi else "")
        self.sp_dmx_step.setValue(float(cue.dmx_step_time))
        self.sp_dmx_chase_loops.setValue(int(cue.dmx_chase_loops))
        self.chk_dmx_pingpong.setChecked(bool(cue.dmx_chase_pingpong))

        # Group-velden
        idx_gmode = self.cb_group_mode.findData(cue.group_mode or "list")
        if idx_gmode >= 0:
            self.cb_group_mode.setCurrentIndex(idx_gmode)
        if cue.cue_type == CueType.GROUP:
            children = self.workspace.children_of(cue.id)
            descendants = self.workspace.descendants_of(cue.id)
            if descendants:
                self.lbl_group_children.setText(
                    f"{len(children)} direct ({len(descendants)} total)"
                )
            else:
                self.lbl_group_children.setText("(none — drag cues in or use right-click)")

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
                  self.ed_net_address, self.ed_net_args, self.btn_net_send,
                  self.ed_dmx_values, self.ed_dmx_chase):
            w.setEnabled(not multi)

        self._updating = False

    def _update_visibility(self, cue_type: str) -> None:
        self.grp_audio.setVisible(cue_type == CueType.AUDIO)
        self.grp_video.setVisible(cue_type == CueType.VIDEO)
        self.grp_image.setVisible(cue_type == CueType.IMAGE)
        self.grp_presentation.setVisible(cue_type == CueType.PRESENTATION)
        self.grp_network.setVisible(cue_type == CueType.NETWORK)
        self.grp_dmx.setVisible(cue_type == CueType.DMX)
        self.grp_wait.setVisible(cue_type == CueType.WAIT)
        self.grp_group.setVisible(cue_type == CueType.GROUP)
        self.grp_target.setVisible(cue_type in (CueType.STOP, CueType.FADE, CueType.START))
        self._update_ppt_visibility()
        self._update_dmx_visibility()
        self._refresh_pro_banner()

    def _update_dmx_visibility(self) -> None:
        """Toon alleen de velden die relevant zijn voor de gekozen DMX-mode:
        snapshot → values + fade-time (fade-time wel zichtbaar maar
        geadviseerd 0); fade → values + fade-time; chase → chase-steps +
        step-time + loops + ping-pong."""
        mode = self.cb_dmx_mode.currentData()
        chase = (mode == "chase")
        # row-index hangt van layout-volgorde af; we zetten gewoon de
        # widgets visible/invisible — labels zijn aan widgets gekoppeld
        # door QFormLayout.
        form = self.grp_dmx.layout()
        for w in (self.ed_dmx_values, self.sp_dmx_fade):
            form.setRowVisible(w, not chase)
        for w in (self.ed_dmx_chase, self.sp_dmx_step,
                  self.sp_dmx_chase_loops, self.chk_dmx_pingpong):
            form.setRowVisible(w, chase)

    def _on_dmx_protocol_change(self) -> None:
        """Wijzig de default-port als de operator van protocol wisselt
        en het port-veld nog op de andere default staat. Voorkomt
        verwarring zoals 'Art-Net op port 5568' wat niet werkt."""
        proto = self.cb_dmx_protocol.currentData()
        cur = self.sp_dmx_port.value()
        if proto == "artnet" and cur == 5568:
            self.sp_dmx_port.setValue(6454)
        elif proto == "sacn" and cur == 6454:
            self.sp_dmx_port.setValue(5568)

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
        # Skip als geen enkele cue daadwerkelijk verandert — voorkomt
        # 'n undo-entry zonder mutatie als de combobox via setEditorData
        # weer dezelfde waarde toont.
        targets = [c for c in self.cues if c.cue_type != new_type]
        if not targets:
            return
        target_ids = [c.id for c in targets]
        sink = getattr(self, "command_sink", None)
        if sink is not None:
            # Via undo-stack zodat type-change undoable is én de
            # showtime-lock 'm netjes blokkeert in plaats van stilletjes
            # door te laten.
            sink.push_set_field(target_ids, "cue_type", new_type)
        else:
            # Test-fallback (geen sink) — direct muteren.
            for c in targets:
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
        target_ids = [c.id for c in targets]
        # Skip als geen enkele cue echt verandert — anders krijg je een
        # undo-entry zonder mutatie (bv. spinbox die op zelfde value blijft).
        if all(getattr(c, attr, None) == value for c in targets):
            return
        sink = getattr(self, "command_sink", None)
        if sink is not None:
            # SetCueFieldCmd.mergeWith zorgt dat opeenvolgende edits op
            # hetzelfde (cue-set, veld) als één undo-stap tellen.
            sink.push_set_field(target_ids, attr, value)
        else:
            # Fallback (tests): direct muteren.
            for c in targets:
                setattr(c, attr, value)
            self.workspace.dirty = True
            self.cue_changed.emit(self.cues[0])

    def _select_color(self, hex_color: str) -> None:
        """Activeer de juiste swatch. Een kleur die niet in CUE_COLORS zit
        (bv. geërfd uit een oudere workspace) wordt door het swatch-
        widget zelf als losse swatch achter de palette toegevoegd."""
        self.cb_color.set_current(hex_color or "")

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
            self, "Choose presentation", "",
            "PowerPoint (*.pptx *.ppt *.pptm);;All files (*)",
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
            self, "Choose video file", "",
            "Video (*.mp4 *.mov *.avi *.mkv *.webm *.m4v);;All files (*)",
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
            self, "Choose image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp);;All files (*)",
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
            self, "Choose audio file", "",
            "Audio (*.wav *.mp3 *.flac *.ogg *.aiff *.aif);;All files (*)",
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

    def _test_send_osc(self) -> None:
        """Verstuur het OSC-bericht uit de Network-groep direct, zonder
        de cue te hoeven afspelen — handig voor het inrichten van
        Companion-knoppen of QLab-cues."""
        from PyQt6.QtWidgets import QMessageBox
        from ..engines.osc_out import parse_args
        if self.osc_out_engine is None:
            QMessageBox.warning(
                self, "OSC output not available",
                "The OSC-output engine is not connected.",
            )
            return
        addr = self.ed_net_address.text().strip()
        host = self.ed_net_host.text().strip() or "127.0.0.1"
        port = self.sp_net_port.value()
        args = parse_args(self.ed_net_args.text())
        ok, err = self.osc_out_engine.send(host, port, addr, args)
        if not ok:
            QMessageBox.warning(self, "OSC send failed", err)
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
                self, "OSC not active",
                "The OSC-input engine is not running. Enable it via "
                "Preferences… and try again.",
            )
            return
        dlg = OscLearnDialog(self.osc_engine, self)
        if dlg.exec() and dlg.learned_address:
            self.ed_trigger_osc.setText(dlg.learned_address)
