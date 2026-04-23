"""Entry point: `python -m livefire` of `python -m livefire.__main__`."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from . import APP_NAME, SETTINGS_ORG, SETTINGS_APP
from .ui import MainWindow, STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName(SETTINGS_ORG)
    app.setApplicationName(SETTINGS_APP)
    app.setApplicationDisplayName(APP_NAME)
    app.setStyleSheet(STYLESHEET)

    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
