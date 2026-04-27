"""Voorkeuren-dialog. Op dit moment alleen audio: output-device + samplerate.
Wijzigingen worden opgeslagen via QSettings en toegepast op de actieve
AudioEngine."""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QDialogButtonBox, QGroupBox,
    QLabel, QLineEdit, QMessageBox, QSpinBox, QCheckBox,
)

from ...engines.audio import (
    AudioEngine, list_output_devices, find_device_index_by_name,
)
from ...engines.audio import register_status as register_audio_status
from ...engines.osc import OscInputEngine, DEFAULT_OSC_PORT
from ...engines.osc import register_status as register_osc_status
from ...engines.osc_feedback import OscFeedbackEngine
from ...engines.osc_feedback import register_status as register_feedback_status
from ...engines.video import VideoEngine, list_audio_devices as list_vlc_audio_devices
from ...i18n import LANGUAGE, SUPPORTED as I18N_SUPPORTED, t


# Default-host voor de Companion-feedback. Companion's OSC-listener
# draait standaard op 127.0.0.1:12321; ouder/zelfde-machine setups
# vinden 'm daar zonder verdere config.
DEFAULT_COMPANION_HOST = "127.0.0.1"
DEFAULT_COMPANION_PORT = 12321
DEFAULT_FEEDBACK_INTERVAL_MS = 100


SUPPORTED_SAMPLE_RATES = [44100, 48000, 96000]
DEFAULT_SAMPLE_RATE = 48000


class PreferencesDialog(QDialog):
    """Dialog voor app-brede voorkeuren (nu: audio-device + samplerate)."""

    def __init__(
        self,
        engine: AudioEngine,
        osc: OscInputEngine | None = None,
        video: VideoEngine | None = None,
        feedback: OscFeedbackEngine | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.engine = engine
        self.osc = osc
        self.video = video
        self.feedback = feedback
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)

        grp = QGroupBox("Audio")
        form = QFormLayout(grp)

        self.cb_device = QComboBox()
        self.cb_device.setToolTip(
            "Audio output device. Choose 'System default' to follow the Windows "
            "default device, otherwise a specific device. The name is stored so "
            "USB reconnects don't break the setting."
        )
        self._populate_devices()
        form.addRow("Output device", self.cb_device)

        self.cb_samplerate = QComboBox()
        self.cb_samplerate.setToolTip(
            "Sample rate the audio engine runs at. Files with a different "
            "sample rate are resampled to this value on load. 48 kHz is the "
            "show standard."
        )
        for sr in SUPPORTED_SAMPLE_RATES:
            self.cb_samplerate.addItem(f"{sr} Hz", sr)
        form.addRow("Sample rate", self.cb_samplerate)

        self.lbl_hint = QLabel(
            "Changes stop all active cues and restart the engine."
        )
        self.lbl_hint.setWordWrap(True)
        form.addRow(self.lbl_hint)

        root.addWidget(grp)

        # ---- OSC -----------------------------------------------------------
        grp_osc = QGroupBox("OSC input")
        osc_form = QFormLayout(grp_osc)
        self.chk_osc_enabled = QCheckBox("Enable OSC input")
        self.chk_osc_enabled.setToolTip(
            "Start/stop the OSC UDP server. On = cues can be triggered "
            "externally via their trigger_osc address."
        )
        self.sp_osc_port = QSpinBox()
        self.sp_osc_port.setRange(1, 65535)
        self.sp_osc_port.setValue(DEFAULT_OSC_PORT)
        self.sp_osc_port.setToolTip(
            "UDP port liveFire listens on. Companion / Stream Deck must use "
            "the same port. Default 53000."
        )
        osc_form.addRow(self.chk_osc_enabled)
        osc_form.addRow("UDP port", self.sp_osc_port)
        root.addWidget(grp_osc)

        # ---- Video --------------------------------------------------------
        grp_video = QGroupBox("Video (libVLC)")
        video_form = QFormLayout(grp_video)
        self.cb_video_audio = QComboBox()
        self.cb_video_audio.setToolTip(
            "Output device for the audio of video cues. libVLC uses its own "
            "device list, separate from the sounddevice audio engine."
        )
        self.cb_video_audio.addItem("System default", "")
        for dev_id, dev_name in list_vlc_audio_devices():
            self.cb_video_audio.addItem(dev_name, dev_id)
        video_form.addRow("Audio device", self.cb_video_audio)
        root.addWidget(grp_video)

        # ---- Companion / OSC feedback -------------------------------------
        grp_comp = QGroupBox("Companion")
        comp_form = QFormLayout(grp_comp)
        self.chk_feedback_enabled = QCheckBox("Push feedback to Companion")
        self.chk_feedback_enabled.setToolTip(
            "Send live transport state (playhead, active count, remaining "
            "time, per-cue state) over OSC to Bitfocus Companion. Drives "
            "Stream Deck variables and feedbacks."
        )
        self.ed_feedback_host = QLineEdit()
        self.ed_feedback_host.setPlaceholderText(DEFAULT_COMPANION_HOST)
        self.ed_feedback_host.setToolTip(
            "Hostname or IP of the machine running Companion. Same machine "
            f"= {DEFAULT_COMPANION_HOST}."
        )
        self.sp_feedback_port = QSpinBox()
        self.sp_feedback_port.setRange(1, 65535)
        self.sp_feedback_port.setValue(DEFAULT_COMPANION_PORT)
        self.sp_feedback_port.setToolTip(
            "UDP port Companion's OSC listener is bound to. Default 12321."
        )
        self.sp_feedback_interval = QSpinBox()
        self.sp_feedback_interval.setRange(20, 1000)
        self.sp_feedback_interval.setSuffix(" ms")
        self.sp_feedback_interval.setValue(DEFAULT_FEEDBACK_INTERVAL_MS)
        self.sp_feedback_interval.setToolTip(
            "How often the playhead/remaining/active snapshot is pushed. "
            "100 ms is smooth without saturating the network."
        )
        comp_form.addRow(self.chk_feedback_enabled)
        comp_form.addRow("Host", self.ed_feedback_host)
        comp_form.addRow("Port", self.sp_feedback_port)
        comp_form.addRow("Interval", self.sp_feedback_interval)
        root.addWidget(grp_comp)

        # ---- Interface (taal) ---------------------------------------------
        grp_iface = QGroupBox("Interface")
        iface_form = QFormLayout(grp_iface)
        self.cb_language = QComboBox()
        self.cb_language.setToolTip(t("prefs.language.tooltip"))
        for code, label in I18N_SUPPORTED:
            self.cb_language.addItem(label, code)
        iface_form.addRow(t("prefs.language"), self.cb_language)
        root.addWidget(grp_iface)

        # Waarden uit QSettings (of huidige engine-config als fallback).
        self._load_from_settings()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- populate ----------------------------------------------------------

    def _populate_devices(self) -> None:
        self.cb_device.clear()
        self.cb_device.addItem("System default", None)
        for d in list_output_devices():
            label = f"{d.name}  ({d.max_output_channels}ch)"
            # userData = device-naam (stabiel tussen runs), niet de index.
            self.cb_device.addItem(label, d.name)

    def _load_from_settings(self) -> None:
        s = QSettings()
        device_name = s.value("audio/device_name", "", type=str)
        sr = s.value("audio/samplerate", DEFAULT_SAMPLE_RATE, type=int)

        if device_name:
            idx = self.cb_device.findData(device_name)
            if idx < 0:
                # Device uit settings bestaat niet meer — voeg "(verdwenen)" toe
                self.cb_device.addItem(f"{device_name}  (not found)", device_name)
                idx = self.cb_device.count() - 1
            self.cb_device.setCurrentIndex(idx)
        else:
            self.cb_device.setCurrentIndex(0)  # Systeem-default

        sr_idx = self.cb_samplerate.findData(sr)
        if sr_idx < 0:
            sr_idx = self.cb_samplerate.findData(DEFAULT_SAMPLE_RATE)
        self.cb_samplerate.setCurrentIndex(max(0, sr_idx))

        self.chk_osc_enabled.setChecked(
            s.value("osc/enabled", False, type=bool)
        )
        self.sp_osc_port.setValue(
            s.value("osc/port", DEFAULT_OSC_PORT, type=int)
        )

        video_dev = s.value("video/audio_device", "", type=str)
        v_idx = self.cb_video_audio.findData(video_dev)
        self.cb_video_audio.setCurrentIndex(v_idx if v_idx >= 0 else 0)

        lang = s.value("app/language", LANGUAGE, type=str)
        l_idx = self.cb_language.findData(lang)
        self.cb_language.setCurrentIndex(l_idx if l_idx >= 0 else 0)

        # Companion / OSC feedback
        self.chk_feedback_enabled.setChecked(
            s.value("companion/enabled", False, type=bool)
        )
        self.ed_feedback_host.setText(
            s.value("companion/host", DEFAULT_COMPANION_HOST, type=str)
        )
        self.sp_feedback_port.setValue(
            s.value("companion/port", DEFAULT_COMPANION_PORT, type=int)
        )
        self.sp_feedback_interval.setValue(
            s.value("companion/interval_ms", DEFAULT_FEEDBACK_INTERVAL_MS, type=int)
        )

    # ---- apply -------------------------------------------------------------

    def _apply_and_accept(self) -> None:
        device_name = self.cb_device.currentData()  # str | None
        sr = self.cb_samplerate.currentData()

        device_arg: int | str | None
        if device_name is None:
            device_arg = None
        else:
            idx = find_device_index_by_name(device_name)
            if idx is None:
                QMessageBox.warning(
                    self, "Device not found",
                    f"The device '{device_name}' is no longer available. "
                    "Choose a different device or use System default.",
                )
                return
            device_arg = idx

        ok, err = self.engine.set_device(device_arg, sample_rate=sr)
        if not ok:
            QMessageBox.critical(
                self, "Cannot restart audio engine",
                f"{err}\n\nThe previous configuration remains active.",
            )
            return

        # Pas na succesvolle herstart schrijven we naar QSettings — zo
        # persisten we nooit een kapotte config.
        s = QSettings()
        s.setValue("audio/device_name", device_name or "")
        s.setValue("audio/samplerate", int(sr))

        # Engine-status registry bijwerken zodat statusbar en Engine-status
        # dialog het nieuwe device tonen.
        register_audio_status(self.engine)

        # OSC toepassen
        if self.osc is not None:
            osc_enabled = self.chk_osc_enabled.isChecked()
            osc_port = int(self.sp_osc_port.value())
            self.osc.stop()
            osc_detail = ""
            if osc_enabled:
                ok, err = self.osc.start(osc_port)
                if not ok:
                    QMessageBox.warning(
                        self, "Cannot start OSC input",
                        f"{err}\n\nOSC remains off.",
                    )
                    osc_enabled = False
            s.setValue("osc/enabled", bool(osc_enabled))
            s.setValue("osc/port", osc_port)
            register_osc_status(self.osc)

        # Video audio-device toepassen (neemt effect vanaf volgende Video-cue)
        video_dev = self.cb_video_audio.currentData() or ""
        s.setValue("video/audio_device", video_dev)
        if self.video is not None:
            self.video.set_audio_device(video_dev)

        # Companion / OSC feedback toepassen
        if self.feedback is not None:
            fb_enabled = self.chk_feedback_enabled.isChecked()
            fb_host = self.ed_feedback_host.text().strip() or DEFAULT_COMPANION_HOST
            fb_port = int(self.sp_feedback_port.value())
            fb_interval = int(self.sp_feedback_interval.value())
            self.feedback.stop()
            if fb_enabled:
                ok, err = self.feedback.start(fb_host, fb_port, fb_interval)
                if not ok:
                    QMessageBox.warning(
                        self, "Cannot start Companion feedback",
                        f"{err}\n\nCompanion feedback remains off.",
                    )
                    fb_enabled = False
            s.setValue("companion/enabled", bool(fb_enabled))
            s.setValue("companion/host", fb_host)
            s.setValue("companion/port", fb_port)
            s.setValue("companion/interval_ms", fb_interval)
            register_feedback_status(self.feedback)

        # Taal opslaan; effect na herstart (sommige strings worden bij
        # module-import al gezet, een live re-render is voor MVP te
        # complex).
        new_lang = self.cb_language.currentData() or "nl"
        old_lang = s.value("app/language", LANGUAGE, type=str)
        s.setValue("app/language", new_lang)
        if new_lang != old_lang:
            QMessageBox.information(
                self,
                t("prefs.language.restart_title"),
                t("prefs.language.restart_body"),
            )

        self.accept()
