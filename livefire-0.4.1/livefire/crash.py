"""Crash-handling: vangt onverwachte exceptions zonder de app te killen.

Probleem dat dit oplost: een onverwachte Python-exception (in een Qt-slot,
worker-thread, of background-timer) trekt nu het hele proces neer. Tijdens
een live show is dat funest — een lopende audio-cue zou abrupt stoppen,
de DMX-output zou bevriezen, en de operator staat met lege handen.

Aanpak:
  - sys.excepthook → schrijft de traceback naar disk + toont een
    non-blocking dialog met "show draait door, save je workspace,
    log staat hier".
  - qInstallMessageHandler → vangt Qt's eigen fatal-msgs (failed
    assertions in C++-laag) en routet ze naar dezelfde log + dialog.
  - threading.excepthook (Py3.8+) → vangt exceptions in non-Qt
    threads, anders verdwijnen die in stilte.

Niet vangen: échte process-fatals (segfaults, OOM-kills). Daar kunnen
we niks aan doen vanuit Python — de OS-laag heeft de boel al gesloopt
voordat onze handler de kans krijgt. Voor die gevallen is autosave
de redding (zie autosave.py).
"""

from __future__ import annotations

import datetime as _dt
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import (
    QStandardPaths, QtMsgType, qInstallMessageHandler,
)


# ---- log-pad ---------------------------------------------------------------

def crash_log_dir() -> Path:
    """Geeft de map waar crash-logs in komen. Op Windows is dat
    typisch ``%APPDATA%\\liveFire\\logs``; op andere platforms volgen
    we Qt's AppDataLocation-conventie. Map wordt aangemaakt als die
    nog niet bestaat."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not base:
        # Extreme fallback — sommige headless setups geven leeg terug.
        base = str(Path.home() / ".livefire")
    p = Path(base) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _new_log_path() -> Path:
    """Pad voor een verse crash-log. Timestamp tot op de seconde
    voorkomt dat twee bijna-tegelijk-crashes elkaars log overschrijven."""
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return crash_log_dir() / f"crash-{stamp}.log"


# ---- writer ----------------------------------------------------------------

def _write_log(header: str, body: str) -> Path:
    """Schrijf een log-record naar een nieuw bestand en geef het pad
    terug. Failure hier mag nooit een tweede exception triggeren —
    daarom een ruime except-vangst en best-effort fallback naar
    sys.stderr."""
    path = _new_log_path()
    try:
        with path.open("w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n")
            f.write("-" * 70)
            f.write("\n")
            f.write(body)
            f.write("\n")
    except Exception as e:  # noqa: BLE001 — write-fail is informatief, niet fataal
        # Als we niet eens kunnen loggen, plak het dan in elk geval
        # op stderr zodat een dev-build z'n console-output bewaart.
        try:
            sys.stderr.write(f"[crash.py] kon log niet schrijven: {e}\n{body}\n")
        except Exception:
            pass
    return path


def _format_header(kind: str) -> str:
    from . import APP_NAME, APP_VERSION  # local import → cycle-vrij

    return (
        f"{APP_NAME} {APP_VERSION} — {kind}\n"
        f"Tijdstip: {_dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"Python:   {sys.version.split()[0]}\n"
        f"Platform: {sys.platform}\n"
        f"Thread:   {threading.current_thread().name}"
    )


# ---- dialog (optioneel) ----------------------------------------------------

# UI-callback. Default = None tijdens tests of vóór install_handlers().
# install_handlers() zet 'm desgewenst op een functie die in de Qt-event-
# thread een non-modale dialog toont.
_dialog_callback: Callable[[str, Path], None] | None = None


def _show_dialog_safely(summary: str, log_path: Path) -> None:
    """Roep de geregistreerde dialog-callback aan, maar vang fouten —
    de crash-handler zelf mag nooit een tweede crash triggeren."""
    cb = _dialog_callback
    if cb is None:
        return
    try:
        cb(summary, log_path)
    except Exception:  # noqa: BLE001
        pass


# ---- handlers ---------------------------------------------------------------

def _excepthook(exc_type, exc_value, exc_tb) -> None:
    # KeyboardInterrupt door laten gaan zodat Ctrl+C in dev-mode werkt.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    header = _format_header("Onverwachte Python-exception")
    log_path = _write_log(header, body)
    summary = f"{exc_type.__name__}: {exc_value}"
    _show_dialog_safely(summary, log_path)


def _thread_excepthook(args) -> None:
    # threading.excepthook-signature is een named-tuple-achtig args-object
    # met exc_type / exc_value / exc_traceback / thread.
    if issubclass(args.exc_type, SystemExit):
        return
    body = "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    )
    header = _format_header(f"Exception in thread {args.thread.name!r}")
    log_path = _write_log(header, body)
    summary = f"{args.exc_type.__name__} in {args.thread.name}: {args.exc_value}"
    _show_dialog_safely(summary, log_path)


def _qt_message_handler(mode, _ctx, message) -> None:
    # We loggen alleen Critical en Fatal — de Qt-laag spamt anders elke
    # Warning naar disk (er zijn er veel, vaak benign).
    if mode not in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        return
    kind = "Qt fatal" if mode == QtMsgType.QtFatalMsg else "Qt critical"
    header = _format_header(kind)
    log_path = _write_log(header, str(message))
    if mode == QtMsgType.QtFatalMsg:
        # Qt zelf gaat hierna toch abort()'en. We tonen de dialog
        # synchroon (zo goed als het lukt) zodat de operator nog ziet
        # wat er gebeurde.
        _show_dialog_safely(f"Qt fatal: {message}", log_path)
    else:
        _show_dialog_safely(f"Qt critical: {message}", log_path)


# ---- public API ------------------------------------------------------------

def install_handlers(dialog_callback: Callable[[str, Path], None] | None = None) -> None:
    """Installeer de drie hooks (sys.excepthook, threading.excepthook,
    qInstallMessageHandler). Optioneel een ``dialog_callback`` die in
    de Qt-event-thread een non-modale dialog toont; signature is
    ``(summary: str, log_path: pathlib.Path) -> None``.

    Idempotent — meerdere keren aanroepen is veilig en overschrijft
    enkel de callback. Bedoeld voor unit-tests die de hooks willen
    resetten via ``uninstall_handlers``."""
    global _dialog_callback
    _dialog_callback = dialog_callback
    sys.excepthook = _excepthook
    # threading.excepthook bestaat sinds Python 3.8.
    threading.excepthook = _thread_excepthook
    qInstallMessageHandler(_qt_message_handler)


def uninstall_handlers() -> None:
    """Reset hooks naar Python's defaults. Vooral nuttig in tests."""
    global _dialog_callback
    _dialog_callback = None
    sys.excepthook = sys.__excepthook__
    threading.excepthook = threading.__excepthook__
    qInstallMessageHandler(None)
