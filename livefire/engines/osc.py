"""OSC input-engine. Luistert op een UDP-poort en emit een Qt-signal voor
elke inkomende message. Bedoeld om cues te triggeren vanaf Companion,
Stream Deck, externe consoles of Max/MSP.

Design:
- python-osc's ``BlockingOSCUDPServer`` draait in een daemon-thread.
- Een catch-all dispatcher ontvangt alle addresses en emit het Qt-signal.
- pyqtSignal is thread-safe over thread-grenzen (auto connection type), dus
  de UI-thread ontvangt het signal netjes via de event-loop.
- Geen auto-start: de UI (MainWindow) start 'm met de geconfigureerde poort.
"""

from __future__ import annotations

import threading
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from .registry import EngineStatus, register

# Optionele dependency — engine werkt degraded zonder.
try:
    from pythonosc.dispatcher import Dispatcher
    from pythonosc.osc_server import BlockingOSCUDPServer
    _OSC_OK = True
    _OSC_ERR = ""
except Exception as e:
    Dispatcher = None  # type: ignore[assignment]
    BlockingOSCUDPServer = None  # type: ignore[assignment]
    _OSC_OK = False
    _OSC_ERR = str(e)


DEFAULT_OSC_HOST = "0.0.0.0"
DEFAULT_OSC_PORT = 53000


class OscInputEngine(QObject):
    """Luistert op een UDP-poort; emit ``message_received(address, args)``.

    - ``address`` is de OSC-address (bv. ``/livefire/go/intro``).
    - ``args`` is een tuple met alle argumenten (kan leeg zijn).
    """

    message_received = pyqtSignal(str, tuple)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._server: "BlockingOSCUDPServer | None" = None
        self._thread: threading.Thread | None = None
        self._host: str = DEFAULT_OSC_HOST
        self._port: int = 0
        self._last_error: str = ""

    # ---- lifecycle ---------------------------------------------------------

    @property
    def available(self) -> bool:
        return _OSC_OK

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        return self._port

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(self, port: int, host: str = DEFAULT_OSC_HOST) -> tuple[bool, str]:
        """Start de server op (host, port). Stopt eerst als er al een draait."""
        if not self.available:
            return False, _OSC_ERR
        self.stop()
        try:
            dispatcher = Dispatcher()  # type: ignore[misc]
            dispatcher.set_default_handler(self._on_osc)
            server = BlockingOSCUDPServer((host, port), dispatcher)  # type: ignore[misc]
        except Exception as e:
            self._last_error = str(e)
            return False, str(e)
        self._server = server
        self._host = host
        self._port = port
        self._thread = threading.Thread(
            target=server.serve_forever, name="osc-input", daemon=True,
        )
        self._thread.start()
        self._last_error = ""
        return True, ""

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        # Wacht kort op de daemon-thread zodat 'ie de UDP-socket echt
        # vrijgeeft vóór we 'm dropppen — anders kan een directe restart op
        # dezelfde poort (bv. via Preferences) een "address already in use"
        # opleveren, en lekken pytest-runs sockets als ResourceWarning.
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._server = None
        self._thread = None
        self._port = 0

    # ---- intern ------------------------------------------------------------

    def _on_osc(self, address: str, *args: Any) -> None:
        """Catch-all handler — draait op de osc-thread. pyqtSignal zorgt voor
        de queued delivery naar de UI-thread."""
        self.message_received.emit(address, tuple(args))


# ---- status-registratie ----------------------------------------------------

def register_status(engine: OscInputEngine | None = None) -> None:
    if not _OSC_OK:
        register(EngineStatus(
            name="OSC-input",
            available=False,
            detail=f"python-osc ontbreekt: {_OSC_ERR}",
            short="osc",
        ))
        return
    if engine is None or not engine.running:
        register(EngineStatus(
            name="OSC-input",
            available=True,
            detail="niet gestart",
            short="osc",
        ))
        return
    register(EngineStatus(
        name="OSC-input",
        available=True,
        detail=f"luistert op {engine._host}:{engine.port}",
        short="osc",
    ))
