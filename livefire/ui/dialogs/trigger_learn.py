"""Modal die wacht op de volgende OSC-message en 'm als trigger-address
teruggeeft. Sluit automatisch zodra er iets binnenkomt."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox

from ...engines.osc import OscInputEngine


class OscLearnDialog(QDialog):
    """Toont 'Wacht op OSC-input…' en vult zichzelf met de eerste address
    die binnenkomt."""

    def __init__(self, engine: OscInputEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.learned_address: str = ""

        self.setWindowTitle("OSC-trigger leren")
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)

        self.lbl_status = QLabel(
            f"Wacht op OSC-input op poort {engine.port}…\n\n"
            "Stuur nu een OSC-message vanaf je console (bv. Companion)."
        )
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.engine.message_received.connect(self._on_message)

    def _on_message(self, address: str, _args: tuple) -> None:
        self.learned_address = address
        self.lbl_status.setText(f"Ontvangen: {address}\n\nDialog sluit automatisch.")
        # Disconnect zodat we maar één message pakken.
        try:
            self.engine.message_received.disconnect(self._on_message)
        except TypeError:
            pass
        self.accept()

    def reject(self) -> None:
        try:
            self.engine.message_received.disconnect(self._on_message)
        except TypeError:
            pass
        super().reject()
