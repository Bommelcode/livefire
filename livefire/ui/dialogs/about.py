from PyQt6.QtWidgets import QMessageBox

from ... import APP_NAME, APP_VERSION


def show_about(parent=None) -> None:
    QMessageBox.about(
        parent,
        f"Over {APP_NAME}",
        f"<b>{APP_NAME}</b> versie {APP_VERSION}<br><br>"
        "Cue-based playback voor Windows live events.<br>"
        "QLab-geïnspireerd, maar Windows-native.<br><br>"
        "Python · PyQt6 · sounddevice",
    )
