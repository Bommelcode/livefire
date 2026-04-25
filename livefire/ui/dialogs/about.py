"""Help → Over liveFire — toont dezelfde splash-pixmap als bij opstart,
in een dialog met een sluitknop in de titlebar."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

from ... import APP_NAME
from ..splash import SPLASH_H, SPLASH_W, build_splash_pixmap


def show_about(parent=None) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Over {APP_NAME}")
    dlg.setFixedSize(SPLASH_W, SPLASH_H)
    # Geen WhatsThisHelp / context-help-knop, alleen sluit-X.
    dlg.setWindowFlags(
        Qt.WindowType.Dialog
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel()
    label.setPixmap(build_splash_pixmap())
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(label)
    dlg.exec()
