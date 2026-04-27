"""OSC-feedback engine — pusht live state naar een externe ontvanger
(typisch Bitfocus Companion) zodat een Stream Deck gevuld kan worden met
knoppen + feedback uit liveFire.

Twee soorten verzending:

* **Periodiek** — om de N ms één snapshot van transport-state. Dit dekt
  variabelen die continu bewegen: playhead-index, aantal actieve cues,
  resterende tijd van de langstlopende audio-cue. Companion's polling-
  interval voor variables is sneller dan deze push, dus je voelt geen
  vertraging.
* **Op-event** — onmiddellijk bij state-changes van losse cues
  (idle/running/finished) en bij workspace-mutaties (cuelist verandert,
  presets moeten herladen).

Adres-schema (verzonden vanaf liveFire → Companion):

* ``/livefire/playhead`` (int, int, string) — index, total, name
* ``/livefire/active`` (int) — aantal actieve cues
* ``/livefire/remaining`` (float) — seconden, negatief bij count-up
* ``/livefire/remaining/label`` (string) — naam van de cue die countdown drijft
* ``/livefire/countdown_active`` (int) — 1=countdown, 0=count-up/idle
* ``/livefire/cue/<cue_number>/state`` (string) — idle / running / finished
* ``/livefire/cue/<cue_number>/name`` (string)
* ``/livefire/cue/<cue_number>/type`` (string) — Audio / Video / etc.
* ``/livefire/cuecount`` (int) — totaal aantal cues in de workspace

De emitter is een QObject zodat 'ie via Qt-signals door de controller
gevoed kan worden, maar gebruikt zelf alleen `python-osc`'s
SimpleUDPClient — geen Qt-thread-magie, geen sounddevice, geen widgets.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .registry import EngineStatus, register


# Optionele dependency — engine werkt degraded zonder.
_OSC_OK = False
_OSC_ERR = ""
try:
    from pythonosc.udp_client import SimpleUDPClient
    _OSC_OK = True
except Exception as _e:
    _OSC_ERR = f"python-osc niet geladen: {_e}"


class OscFeedbackEngine(QObject):
    """Pusht state-updates over UDP naar een geconfigureerde ontvanger.

    Roep ``start(host, port, interval_ms)`` aan om de UDP-client op te
    zetten en de periodieke push te starten. ``stop()`` verbreekt de
    socket. ``send_*`` methodes kunnen los worden aangeroepen voor on-
    event pushes (bv. zodra een cue van state wisselt).
    """

    # Interval default: 100 ms = 10 Hz. Snel genoeg voor smooth countdown
    # in Companion-variables, niet zo snel dat je netwerk en CPU stresst.
    DEFAULT_INTERVAL_MS = 100

    feedback_failed = pyqtSignal(str)  # error voor UI-statusbar

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._client = None
        self._host: str = ""
        self._port: int = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        # Snapshot-providers — MainWindow drukt callbacks in zodat we
        # zonder circulaire imports bij de live state kunnen.
        self._provider = None
        self._last_error: str = ""

    @property
    def available(self) -> bool:
        return _OSC_OK

    @property
    def running(self) -> bool:
        return self._client is not None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def last_error(self) -> str:
        return self._last_error

    def set_provider(self, provider) -> None:
        """Bind een snapshot-provider die de transport-state samenstelt.

        Het provider-object moet ``snapshot()`` ondersteunen, returning:

        ``{
            "playhead": int,
            "playhead_total": int,
            "playhead_name": str,
            "active": int,
            "remaining": float,        # negatief = count-up
            "remaining_label": str,
            "countdown_active": bool,
        }``

        Dit pad maakt de emitter Qt-widget-vrij — MainWindow weet wel hoe
        je een snapshot maakt; deze engine niet.
        """
        self._provider = provider

    # ---- public API --------------------------------------------------------

    def start(
        self,
        host: str,
        port: int,
        interval_ms: int = DEFAULT_INTERVAL_MS,
    ) -> tuple[bool, str]:
        if not _OSC_OK:
            self._last_error = _OSC_ERR or "python-osc niet beschikbaar"
            return False, self._last_error
        if not host:
            self._last_error = "Host is leeg"
            return False, self._last_error
        if port <= 0 or port > 65535:
            self._last_error = f"Port out of range: {port}"
            return False, self._last_error

        self.stop()
        try:
            self._client = SimpleUDPClient(host, int(port))
        except Exception as e:
            self._client = None
            self._last_error = str(e)
            return False, self._last_error
        self._host = host
        self._port = int(port)
        self._timer.setInterval(max(20, int(interval_ms)))
        self._timer.start()
        self._last_error = ""
        return True, ""

    def stop(self) -> None:
        self._timer.stop()
        if self._client is not None:
            sock = getattr(self._client, "_sock", None)
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
        self._client = None

    def shutdown(self) -> None:
        self.stop()

    # ---- senders -----------------------------------------------------------

    def send(self, address: str, *args: Any) -> None:
        """Stuur één OSC-bericht. Faalt stil — een transient netwerk-
        glitch op een single-show OSC-link mag de show niet stoppen, maar
        we sturen een ``feedback_failed``-signal voor de statusbar."""
        if self._client is None:
            return
        try:
            self._client.send_message(address, list(args))
        except Exception as e:
            self._last_error = str(e)
            self.feedback_failed.emit(str(e))

    def send_cue_state(self, cue_number: str, state: str) -> None:
        if not cue_number:
            return
        self.send(f"/livefire/cue/{cue_number}/state", state)

    def send_cue_meta(self, cue_number: str, name: str, cue_type: str) -> None:
        """Naam + type van een cue — door MainWindow geëmit na elke
        workspace-mutatie zodat Companion's preset-labels meebewegen."""
        if not cue_number:
            return
        self.send(f"/livefire/cue/{cue_number}/name", name or "")
        self.send(f"/livefire/cue/{cue_number}/type", cue_type or "")

    def send_cuecount(self, count: int) -> None:
        self.send("/livefire/cuecount", int(count))

    # ---- intern ------------------------------------------------------------

    def _on_tick(self) -> None:
        if self._provider is None or self._client is None:
            return
        try:
            snap = self._provider.snapshot()
        except Exception as e:
            self._last_error = str(e)
            self.feedback_failed.emit(str(e))
            return
        if not snap:
            return
        self.send(
            "/livefire/playhead",
            int(snap.get("playhead", 0)),
            int(snap.get("playhead_total", 0)),
            str(snap.get("playhead_name", "")),
        )
        self.send("/livefire/active", int(snap.get("active", 0)))
        self.send("/livefire/remaining", float(snap.get("remaining", 0.0)))
        self.send(
            "/livefire/remaining/label",
            str(snap.get("remaining_label", "")),
        )
        self.send(
            "/livefire/countdown_active",
            1 if snap.get("countdown_active", False) else 0,
        )


def register_status(engine: OscFeedbackEngine | None = None) -> None:
    if not _OSC_OK:
        register(EngineStatus(
            name="OSC feedback (Companion)",
            available=False,
            detail=_OSC_ERR,
            short="osc-fb",
        ))
        return
    if engine is not None and engine.running:
        detail = f"Pushing → {engine.host}:{engine.port}"
    elif engine is not None and engine.last_error:
        detail = f"Off — last error: {engine.last_error}"
    else:
        detail = "Idle (configure under Preferences → Companion)"
    register(EngineStatus(
        name="OSC feedback (Companion)",
        available=True,
        detail=detail,
        short="osc-fb",
    ))
