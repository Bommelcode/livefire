"""Entry point: `python -m livefire` of `python -m livefire.__main__`."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import ctypes
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QSplashScreen

from . import APP_NAME, SETTINGS_ORG, SETTINGS_APP
from .ui import MainWindow, build_stylesheet
from .ui.splash import build_splash_pixmap


_ICON_PATH = Path(__file__).parent / "resources" / "icon.png"
_SPLASH_DURATION_S = 3.5


def main() -> int:
    # Op Windows moeten we de AppUserModelID zetten voor we de QApplication
    # bouwen, anders groepeert de taskbar onze app onder "Python" in plaats
    # van een eigen entry met ons icoon te tonen.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"{SETTINGS_ORG}.{SETTINGS_APP}"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setOrganizationName(SETTINGS_ORG)
    app.setApplicationName(SETTINGS_APP)
    app.setApplicationDisplayName(APP_NAME)
    if _ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))
    app.setStyleSheet(build_stylesheet())

    w = MainWindow()
    w.show()
    app.processEvents()

    # Splashscreen ná w.show() zodat 'ie boven de hoofd-UI verschijnt.
    # WindowStaysOnTopHint houdt 'm zichtbaar tijdens de _SPLASH_DURATION_S.
    if _ICON_PATH.is_file():
        splash = QSplashScreen(build_splash_pixmap(),
                               Qt.WindowType.WindowStaysOnTopHint)
        splash.show()
        app.processEvents()
        started = time.monotonic()
        while time.monotonic() - started < _SPLASH_DURATION_S:
            app.processEvents()
            time.sleep(0.03)
        splash.finish(w)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
