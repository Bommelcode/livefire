"""Entry point: `python -m livefire` of `python -m livefire.__main__`."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import ctypes
from PyQt6.QtCore import Qt, QCoreApplication, QSettings, QSharedMemory
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from . import APP_NAME, SETTINGS_ORG, SETTINGS_APP
from .i18n import set_language


_ICON_PATH = Path(__file__).parent / "resources" / "icon.png"
_SPLASH_DURATION_S = 3.5

# Singleton-key voor de QSharedMemory-segment. Versionering ingebakken
# zodat een toekomstige format-bump niet botst met een oude instance
# die nog draait tijdens een upgrade.
_SINGLETON_KEY = "livefire-singleton-v1"


def _acquire_single_instance_lock(app: QApplication) -> QSharedMemory | None:
    """Probeer een proces-brede lock te claimen. Returns de shared-memory
    handle (die actief blijft zolang de app draait) of None als er al een
    andere instance draait — in dat geval is er een nette dialog getoond
    en moet de caller met exitcode != 0 afsluiten.

    Werkt op Windows, macOS en Linux: QSharedMemory wraps Win32 named
    objects respectievelijk POSIX shm. De kernel ruimt de segment auto-
    matisch op wanneer het proces eindigt (ook bij crash), dus stale
    locks zijn zeldzaam.
    """
    shm = QSharedMemory(_SINGLETON_KEY)
    # attach() lukt alleen wanneer een andere instance de segment al
    # heeft aangemaakt — dat is het signaal dat er al een liveFire
    # draait.
    if shm.attach():
        shm.detach()
        QMessageBox.warning(
            None,
            "liveFire is already running",
            "Another instance of liveFire is already running on this machine.\n\n"
            "Switch to that window instead — running two at once would clash on "
            "the OSC-input port and audio device.",
        )
        return None
    if not shm.create(1):
        # Onverwachte fout (geen permissions, OS-resource-limit, ...).
        QMessageBox.critical(
            None,
            "Cannot start liveFire",
            "Failed to acquire single-instance lock:\n\n"
            f"{shm.errorString()}",
        )
        return None
    # Houd 'm aan de QApplication zodat hij niet door de garbage-
    # collector wordt opgeruimd vóór app-exit.
    app._singleton_shm = shm  # type: ignore[attr-defined]
    return shm


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

    # Lees taal-setting voordat we UI-modules importeren — sommige module-
    # level strings (bv. cuelist-kolomtitels) worden bij import al gezet.
    QCoreApplication.setOrganizationName(SETTINGS_ORG)
    QCoreApplication.setApplicationName(SETTINGS_APP)
    set_language(QSettings().value("app/language", "en", type=str))

    # Crash-handlers vroeg installeren — vóór UI-imports — zodat zelfs
    # een exception in MainWindow.__init__ in een log-bestand belandt
    # in plaats van in een onzichtbare console. De UI-callback die
    # daadwerkelijk een dialog toont wordt later vanuit MainWindow
    # geregistreerd; voor nu schrijft crash.py alleen naar disk.
    from . import crash as crash_mod
    crash_mod.install_handlers()

    # Imports hier zodat ze de juiste taal-strings oppakken.
    from .ui import MainWindow, build_stylesheet
    from .ui.splash import build_splash_pixmap

    app = QApplication(sys.argv)
    app.setOrganizationName(SETTINGS_ORG)
    app.setApplicationName(SETTINGS_APP)
    app.setApplicationDisplayName(APP_NAME)

    # Visual Studio-stijl UI-font: Segoe UI 9pt op de QApplication zelf
    # zodat álle widgets (incl. native dialogs en sub-windows zonder eigen
    # stylesheet-regel) 'm overnemen. De stylesheet zet 't ook nog
    # expliciet op QMainWindow/QWidget voor consistentie.
    app.setFont(QFont("Segoe UI", 9))

    if _ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))
    app.setStyleSheet(build_stylesheet())

    # Single-instance gate. Twee instances tegelijk botsen op de OSC-
    # input UDP-poort, het audio-device en het Companion-feedback-pad —
    # dus verbieden we 't meteen met een nette dialog ipv te wachten
    # tot één van de engines met een WinError 10048 omvalt.
    if _acquire_single_instance_lock(app) is None:
        return 1

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
