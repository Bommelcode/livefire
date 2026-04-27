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

        self.setWindowTitle("Learn OSC trigger")
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)

        self.lbl_status = QLabel(
            f"Waiting for OSC input on port {engine.port}…\n\n"
            "Send an OSC message from your console (e.g. Companion) now."
        )
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.engine.message_received.connect(self._on_message)

    def _disconnect(self) -> None:
        """Idempotent disconnect — voorkomt RuntimeError als de dialog op
        een andere manier wordt gedestroyed (bv. parent-window sluit) en
        er daarna nog een OSC-bericht binnenkomt op een gedelete object."""
        try:
            self.engine.message_received.disconnect(self._on_message)
        except TypeError:
            pass

    def _on_message(self, address: str, _args: tuple) -> None:
        self.learned_address = address
        self.lbl_status.setText(f"Received: {address}\n\nDialog will close automatically.")
        self._disconnect()
        self.accept()

    def reject(self) -> None:
        self._disconnect()
        super().reject()

    def closeEvent(self, e) -> None:  # type: ignore[override]
        self._disconnect()
        super().closeEvent(e)
