"""Voorkeuren-dialog. Op dit moment alleen audio: output-device + samplerate.
Wijzigingen worden opgeslagen via QSettings en toegepast op de actieve
AudioEngine."""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QDialogButtonBox, QGroupBox,
    QLabel, QMessageBox, QSpinBox, QCheckBox,
)

from ...engines.audio import (
    AudioEngine, list_output_devices, find_device_index_by_name,
)
from ...engines.audio import register_status as register_audio_status
from ...engines.osc import OscInputEngine, DEFAULT_OSC_PORT
from ...engines.osc import register_status as register_osc_status
from ...engines.video import VideoEngine, list_audio_devices as list_vlc_audio_devices
from ...i18n import LANGUAGE, SUPPORTED as I18N_SUPPORTED, t


SUPPORTED_SAMPLE_RATES = [44100, 48000, 96000]
DEFAULT_SAMPLE_RATE = 48000


class PreferencesDialog(QDialog):
    """Dialog voor app-brede voorkeuren (nu: audio-device + samplerate)."""

    def __init__(
        self,
        engine: AudioEngine,
        osc: OscInputEngine | None = None,
        video: VideoEngine | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.engine = engine
        self.osc = osc
        self.video = video
        self.setWindowTitle("Voorkeuren")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)

        grp = QGroupBox("Audio")
        form = QFormLayout(grp)

        self.cb_device = QComboBox()
        self.cb_device.setToolTip(
            "Audio output-device. Kies 'Systeem-default' om het Windows-default device "
            "te volgen, anders een specifiek apparaat. Naam wordt opgeslagen zodat "
            "USB-herconnects geen invloed hebben."
        )
        self._populate_devices()
        form.addRow("Output-device", self.cb_device)

        self.cb_samplerate = QComboBox()
        self.cb_samplerate.setToolTip(
            "Samplerate waar de audio-engine op draait. Bestanden met een andere "
            "samplerate worden bij het laden geresampled naar deze waarde. "
            "48 kHz is show-standaard."
        )
        for sr in SUPPORTED_SAMPLE_RATES:
            self.cb_samplerate.addItem(f"{sr} Hz", sr)
        form.addRow("Samplerate", self.cb_samplerate)

        # WASAPI exclusive — alleen zinvol op Windows. Op andere platforms
        # negeert de engine de flag, maar we tonen 'm consequent zodat
        # cross-platform shows dezelfde voorkeur behouden.
        self.chk_exclusive = QCheckBox("WASAPI exclusive mode (Windows)")
        self.chk_exclusive.setToolTip(
            "Claim het audio-device exclusief via Windows' WASAPI host API. "
            "Voordeel: Windows mixer overrulet niet meer (geen samplerate-"
            "conversie, lagere latency, bit-perfecte output). Nadeel: andere "
            "apps krijgen geen audio meer zolang liveFire draait, en als een "
            "andere app het device al heeft mislukt het openen — dan valt "
            "liveFire automatisch terug op shared mode."
        )
        form.addRow("Exclusive mode", self.chk_exclusive)

        self.lbl_hint = QLabel(
            "Wijzigingen stoppen alle actieve cues en herstarten de engine."
        )
        self.lbl_hint.setWordWrap(True)
        form.addRow(self.lbl_hint)

        root.addWidget(grp)

        # ---- OSC -----------------------------------------------------------
        grp_osc = QGroupBox("OSC-input")
        osc_form = QFormLayout(grp_osc)
        self.chk_osc_enabled = QCheckBox("OSC-input inschakelen")
        self.chk_osc_enabled.setToolTip(
            "Start/stop de OSC-UDP-server. Aan = cues kunnen van buitenaf getriggerd "
            "worden via hun trigger_osc-address."
        )
        self.sp_osc_port = QSpinBox()
        self.sp_osc_port.setRange(1, 65535)
        self.sp_osc_port.setValue(DEFAULT_OSC_PORT)
        self.sp_osc_port.setToolTip(
            "UDP-poort waar liveFire op luistert. Companion / Stream Deck moeten dezelfde "
            "poort gebruiken. Default 53000."
        )
        osc_form.addRow(self.chk_osc_enabled)
        osc_form.addRow("UDP-poort", self.sp_osc_port)
        root.addWidget(grp_osc)

        # ---- Video --------------------------------------------------------
        grp_video = QGroupBox("Video (libVLC)")
        video_form = QFormLayout(grp_video)
        self.cb_video_audio = QComboBox()
        self.cb_video_audio.setToolTip(
            "Output-device voor de audio van video-cues. libVLC gebruikt z'n "
            "eigen device-lijst, los van de sounddevice audio-engine."
        )
        self.cb_video_audio.addItem("Systeem-default", "")
        for dev_id, dev_name in list_vlc_audio_devices():
            self.cb_video_audio.addItem(dev_name, dev_id)
        video_form.addRow("Audio-device", self.cb_video_audio)
        root.addWidget(grp_video)

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
        self.cb_device.addItem("Systeem-default", None)
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
                self.cb_device.addItem(f"{device_name}  (niet gevonden)", device_name)
                idx = self.cb_device.count() - 1
            self.cb_device.setCurrentIndex(idx)
        else:
            self.cb_device.setCurrentIndex(0)  # Systeem-default

        sr_idx = self.cb_samplerate.findData(sr)
        if sr_idx < 0:
            sr_idx = self.cb_samplerate.findData(DEFAULT_SAMPLE_RATE)
        self.cb_samplerate.setCurrentIndex(max(0, sr_idx))

        self.chk_exclusive.setChecked(
            s.value("audio/exclusive_mode", False, type=bool)
        )

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
                    self, "Device niet gevonden",
                    f"Het device '{device_name}' is niet (meer) beschikbaar. "
                    "Kies een ander device of gebruik Systeem-default.",
                )
                return
            device_arg = idx

        exclusive = self.chk_exclusive.isChecked()
        ok, err = self.engine.set_device(
            device_arg, sample_rate=sr, exclusive_mode=exclusive,
        )
        if not ok:
            QMessageBox.critical(
                self, "Kan audio-engine niet herstarten",
                f"{err}\n\nDe oude configuratie blijft actief.",
            )
            return

        # Pas na succesvolle herstart schrijven we naar QSettings — zo
        # persisten we nooit een kapotte config.
        s = QSettings()
        s.setValue("audio/device_name", device_name or "")
        s.setValue("audio/samplerate", int(sr))
        s.setValue("audio/exclusive_mode", exclusive)

        # Als de engine fallback heeft gedaan naar shared mode (bv. omdat
        # exclusive open mislukte), waarschuwen we de gebruiker zodat ze
        # weten waar ze aan toe zijn — anders is "exclusive aan" een
        # silent leugen.
        if exclusive and self.engine._last_error and "shared" in self.engine._last_error.lower():
            QMessageBox.information(
                self, "Exclusive mode niet beschikbaar",
                self.engine._last_error
                + "\n\nLiveFire draait nu in shared mode.",
            )

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
                        self, "Kan OSC-input niet starten",
                        f"{err}\n\nOSC blijft uit.",
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
