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


SUPPORTED_SAMPLE_RATES = [44100, 48000, 96000]
DEFAULT_SAMPLE_RATE = 48000


class PreferencesDialog(QDialog):
    """Dialog voor app-brede voorkeuren (nu: audio-device + samplerate)."""

    def __init__(
        self,
        engine: AudioEngine,
        osc: OscInputEngine | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.engine = engine
        self.osc = osc
        self.setWindowTitle("Voorkeuren")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)

        grp = QGroupBox("Audio")
        form = QFormLayout(grp)

        self.cb_device = QComboBox()
        self._populate_devices()
        form.addRow("Output-device", self.cb_device)

        self.cb_samplerate = QComboBox()
        for sr in SUPPORTED_SAMPLE_RATES:
            self.cb_samplerate.addItem(f"{sr} Hz", sr)
        form.addRow("Samplerate", self.cb_samplerate)

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
        self.sp_osc_port = QSpinBox()
        self.sp_osc_port.setRange(1, 65535)
        self.sp_osc_port.setValue(DEFAULT_OSC_PORT)
        osc_form.addRow(self.chk_osc_enabled)
        osc_form.addRow("UDP-poort", self.sp_osc_port)
        root.addWidget(grp_osc)

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

        self.chk_osc_enabled.setChecked(
            s.value("osc/enabled", False, type=bool)
        )
        self.sp_osc_port.setValue(
            s.value("osc/port", DEFAULT_OSC_PORT, type=int)
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
                    self, "Device niet gevonden",
                    f"Het device '{device_name}' is niet (meer) beschikbaar. "
                    "Kies een ander device of gebruik Systeem-default.",
                )
                return
            device_arg = idx

        ok, err = self.engine.set_device(device_arg, sample_rate=sr)
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

        self.accept()
