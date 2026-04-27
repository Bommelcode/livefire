"""OSC-out engine voor Network-cues.

Stuurt UDP OSC-messages naar een opgegeven host:port. Gebruikt
``python-osc`` (al een dependency voor de OSC-input). Verbindingsloos —
iedere ``send()`` opent z'n eigen `SimpleUDPClient`. Geen retries, geen
queue: OSC over UDP is best-effort. Voor cue-triggering naar Companion,
QLab, een SQ5 of een ander OSC-aware apparaat is dat ruim voldoende.

Argument-parsing
----------------
Cue-velden bewaren OSC-args als één tekstveld. ``parse_args(s)`` splitst
op komma's en bepaalt per token het type:

  * ``42``      → int
  * ``1.5``     → float
  * ``"hi all"``→ string (quotes verwijderd, spaties bewaard)
  * ``hello``   → string

Voorbeelden:
  ``"channel", 1, 0.5``    → ["channel", 1, 0.5]
  ``true``                  → "true" (string — OSC heeft geen native bool;
                              ontvanger interpreteert zelf)
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from .registry import EngineStatus, register


# Optionele dependency — engine werkt degraded zonder.
_OSC_OK = False
_OSC_ERR = ""
try:
    from pythonosc.udp_client import SimpleUDPClient
    _OSC_OK = True
except Exception as _e:
    _OSC_ERR = f"python-osc niet geladen: {_e}"


def parse_args(text: str) -> list:
    """Parseer een door komma's gescheiden tekstveld naar OSC-args.

    Type-resolutie volgt OSC-conventies: een **gequote** token wordt
    altijd als string doorgegeven (zelfs als het er als getal uitziet),
    een **niet-gequote** token wordt eerst als int, dan als float, en
    anders als string geïnterpreteerd. Whitespace **buiten** quotes
    wordt aan begin/eind gestript; whitespace **binnen** quotes blijft
    onveranderd, evenals komma's binnen quotes (geen token-split).

    Voorbeelden::

        parse_args('1, 0.5, hello')         → [1, 0.5, 'hello']
        parse_args('"42"')                  → ['42']      # quoted = string
        parse_args('"hello, world"')        → ['hello, world']
        parse_args('" "')                   → [' ']        # quoted whitespace blijft
        parse_args('1, "hello"')            → [1, 'hello'] # whitespace buiten quote weg
        parse_args('1, , 2')                → [1, 2]      # leeg token weggevallen
    """
    if not text:
        return []

    # Tokeniseer met per-karakter quote-tracking. Iedere token is een lijst
    # van (char, was_in_quote)-paren zodat we bij het strippen van
    # leading/trailing whitespace alléén onquoted spaties verwijderen.
    tokens: list[list[tuple[str, bool]]] = []
    cur: list[tuple[str, bool]] = []
    quote: str | None = None
    for ch in text:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                cur.append((ch, True))
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == ",":
            tokens.append(cur)
            cur = []
            continue
        cur.append((ch, False))
    tokens.append(cur)

    out: list = []
    for token in tokens:
        # Strip leading/trailing whitespace die NIET binnen quotes zat.
        while token and not token[0][1] and token[0][0].isspace():
            token.pop(0)
        while token and not token[-1][1] and token[-1][0].isspace():
            token.pop()
        if not token:
            continue
        had_quote = any(q for _, q in token)
        s = "".join(ch for ch, _ in token)
        if had_quote:
            # Expliciet gequoot ergens in het token → string, geen
            # type-coercion. "42" blijft string, " " (gequoot) blijft " ".
            out.append(s)
            continue
        # Pure unquoted: probeer int → float → string.
        try:
            out.append(int(s))
            continue
        except ValueError:
            pass
        try:
            out.append(float(s))
            continue
        except ValueError:
            pass
        out.append(s)
    return out


class OscOutputEngine(QObject):
    """Stuurt OSC-messages naar een opgegeven host:port. Hergebruikt
    `SimpleUDPClient`-instances per ``(host, port)``-combinatie zodat we
    niet voor iedere cue een nieuwe socket openen — bij snelle Network-
    cue chains zou dat de ephemeral-port range kunnen uitputten of
    sockets in TIME_WAIT achterlaten."""

    message_sent = pyqtSignal(str, int, str)  # host, port, address — voor UI/logging

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._clients: dict[tuple[str, int], "SimpleUDPClient"] = {}

    @property
    def available(self) -> bool:
        return _OSC_OK

    def _get_client(self, host: str, port: int) -> "SimpleUDPClient":
        key = (host, port)
        client = self._clients.get(key)
        if client is None:
            # SimpleUDPClient resolveert de host bij constructie; bij een
            # hostname (geen IP) blokkeert dat op DNS. In productie
            # raden we IPs aan in de cue-velden.
            client = SimpleUDPClient(host, port)
            self._clients[key] = client
        return client

    @staticmethod
    def _close_client(client) -> None:
        """Sluit het UDP-socket van een SimpleUDPClient best-effort.
        ``_sock`` is een privé-attribuut van python-osc maar staat al
        sinds v1.7 stabiel; voor andere objecten (bv. een test-stub die
        per ongeluk in de cache zit) doen we niets."""
        try:
            sock = getattr(client, "_sock", None)
            if sock is not None:
                sock.close()
        except Exception:
            pass

    def send(
        self, host: str, port: int, address: str, args: list,
    ) -> tuple[bool, str]:
        """Stuur ``address`` met ``args`` naar ``host:port``.

        Returnt ``(ok, error)``. Bij ``ok=False`` bevat ``error`` een
        bruikbare melding voor de UI; de cue-runner kan zelf besluiten
        of dat een fatale fout is voor de cue."""
        if not _OSC_OK:
            return False, _OSC_ERR or "python-osc niet beschikbaar"
        if not address:
            return False, "OSC-address is leeg"
        if not address.startswith("/"):
            return False, "OSC-address moet met '/' beginnen"
        if not host:
            return False, "Host is leeg"
        try:
            port_i = int(port)
        except (TypeError, ValueError):
            return False, f"Ongeldige port: {port!r}"
        if port_i <= 0 or port_i > 65535:
            return False, f"Port buiten range: {port_i}"
        try:
            client = self._get_client(host, port_i)
            client.send_message(address, args)
        except Exception as e:
            # Verwijder een mogelijk corrupte cached client zodat een
            # volgende send opnieuw probeert te resolven. Sluit z'n socket
            # zodat de fd niet pas bij GC vrijkomt (zou een ResourceWarning
            # opleveren bij snelle send-loops met steeds falende host).
            evicted = self._clients.pop((host, port_i), None)
            if evicted is not None:
                self._close_client(evicted)
            return False, f"Versturen mislukt: {e}"
        self.message_sent.emit(host, port_i, address)
        return True, ""

    def shutdown(self) -> None:
        """Sluit eventuele cached UDP-clients (ze hebben elk een socket)."""
        for client in self._clients.values():
            self._close_client(client)
        self._clients.clear()


def register_status(engine: OscOutputEngine | None = None) -> None:
    if not _OSC_OK:
        register(EngineStatus(
            name="OSC-output",
            available=False,
            detail=_OSC_ERR,
            short="osc-out",
        ))
        return
    register(EngineStatus(
        name="OSC-output",
        available=True,
        detail="UDP OSC-messages versturen via python-osc.",
        short="osc-out",
    ))
