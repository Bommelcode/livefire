"""DMX-engine — Art-Net + sACN (E1.31).

Beide protocollen encoderen we zelf met ``struct`` + raw UDP zodat we
geen externe asynchrone library hoeven mee te slepen die botst met onze
QTimer-gebaseerde controller.

Architectuur
------------

* Per (protocol, universe)-combinatie houdt de engine een 512-byte
  ``Universe``-buffer in geheugen. Cues schrijven hun waardes in deze
  buffer (LTP — latere cue overschrijft oudere op dezelfde channels).
* Een achtergrondthread (``_send_loop``) pusht alle bekende universes
  continu door op de geconfigureerde refresh-rate (default 30 Hz) zodat
  consoles/dimmers de stream "alive" zien.
* DMX-cues registreren zichzelf bij de engine als snapshot, fade, of
  chase. ``_send_loop`` interpoleert per tick voor lopende fades en
  schuift door voor lopende chases.

Cue-types worden via ``play()``/``stop_cue()`` als generieke handles
beheerd; de controller hoeft niets te weten van fades/chase-states.

Threading
---------
De sender-thread leest universe-buffers en schrijft state-machines
voor fade/chase via een ``threading.Lock``. Public methodes
(play/stop_cue/shutdown) lopen op de Qt-hoofdthread en grijpen de
lock kort om het delta in te dragen.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from PyQt6.QtCore import QObject, pyqtSignal

from .registry import EngineStatus, register


# ---- protocol-constanten ---------------------------------------------------

ARTNET_PORT = 6454
SACN_PORT = 5568

ARTNET_HEADER_MAGIC = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000
ARTNET_PROTOCOL_VERSION = 14

SACN_PREAMBLE_SIZE = 0x0010
SACN_POSTAMBLE_SIZE = 0
SACN_PACKET_IDENT = b"ASC-E1.17\x00\x00\x00"


# ---- value-parser ----------------------------------------------------------

def parse_dmx_values(text: str) -> dict[int, int]:
    """Parseer een tekstveld ``"1:255, 17:128, 33:64"`` naar
    ``{channel: value}``. Tolerant voor extra whitespace + lege tokens.

    Channels worden geklemd op 1..512, waardes op 0..255. Onleesbare
    tokens worden stilzwijgend overgeslagen — een typo mag de hele cue
    niet onderuit halen tijdens een show.
    """
    result: dict[int, int] = {}
    if not text:
        return result
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            continue
        ch_s, val_s = token.split(":", 1)
        try:
            ch = int(ch_s.strip())
            val = int(val_s.strip())
        except ValueError:
            continue
        if 1 <= ch <= 512 and 0 <= val <= 255:
            result[ch] = val
    return result


def parse_chase_steps(text: str) -> list[dict[int, int]]:
    """``"1:255 | 1:0,17:128 | 17:255"`` → drie stap-snapshots.

    Lege strings tussen ``|`` leveren een lege snapshot — handig om
    een "blackout"-step in een chase te bouwen zonder een speciaal
    syntax."""
    if not text:
        return []
    return [parse_dmx_values(part) for part in text.split("|")]


# ---- packet encoders -------------------------------------------------------

def encode_artnet_dmx(universe: int, sequence: int, dmx: bytes) -> bytes:
    """ArtDMX-packet (OpCode 0x5000).

    universe = 0..32767 — split in lower-7-bit subnet/universe en upper
    bits voor net. We zetten 'm direct als little-endian uint16.
    sequence = 0..255 (0 = disabled). dmx = exact 512 bytes.
    """
    if len(dmx) != 512:
        raise ValueError(f"DMX payload moet 512 bytes zijn, kreeg {len(dmx)}")
    universe = universe & 0x7FFF
    sequence = sequence & 0xFF
    physical = 0
    length = 512
    return (
        ARTNET_HEADER_MAGIC
        + struct.pack("<H", ARTNET_OPCODE_DMX)
        + struct.pack(">H", ARTNET_PROTOCOL_VERSION)
        + struct.pack(">BB", sequence, physical)
        + struct.pack("<H", universe)
        + struct.pack(">H", length)
        + dmx
    )


# 16-byte UUID-achtige bytes per ANSI E1.31 spec (CID-veld is een UUID).
# Vaste waarde is acceptabel — het CID identificeert "deze sender", en
# liveFire spreekt vanuit één proces.
_SACN_CID = bytes.fromhex("4c69766546697265436f6d70616e696f6e")[:16]


def encode_sacn_dmx(universe: int, sequence: int, dmx: bytes,
                    source_name: str = "liveFire") -> bytes:
    """ANSI E1.31 (sACN) DATA packet. Drie lagen: Root, Framing, DMP.

    De ID-velden hieronder zijn voorgeschreven door de spec; de offsets
    en lengtes ook. Dit is ~126 bytes header + 513 bytes (start-code
    0x00 + 512 channels) = 638 bytes totaal voor één universe-frame.
    """
    if len(dmx) != 512:
        raise ValueError(f"DMX payload moet 512 bytes zijn, kreeg {len(dmx)}")
    universe = universe & 0xFFFF
    sequence = sequence & 0xFF

    name_bytes = source_name.encode("utf-8")[:64].ljust(64, b"\x00")

    # ---- Root layer (38 bytes)
    root = struct.pack(">H", SACN_PREAMBLE_SIZE)
    root += struct.pack(">H", SACN_POSTAMBLE_SIZE)
    root += SACN_PACKET_IDENT
    # Flags+Length: PDU-length = total - 16 (preamble/postamble); flags 0x7
    pdu_length_root = 0x7000 | (638 - 16)
    root += struct.pack(">H", pdu_length_root)
    root += struct.pack(">I", 0x00000004)  # vector ROOT_E131_DATA
    root += _SACN_CID

    # ---- Framing layer (77 bytes)
    framing = b""
    pdu_length_framing = 0x7000 | (638 - 38)
    framing += struct.pack(">H", pdu_length_framing)
    framing += struct.pack(">I", 0x00000002)  # vector E131_DATA_PACKET
    framing += name_bytes
    framing += struct.pack(">B", 100)         # Priority
    framing += struct.pack(">H", 0)           # Synchronization Address
    framing += struct.pack(">B", sequence)    # Sequence Number
    framing += struct.pack(">B", 0)           # Options
    framing += struct.pack(">H", universe)    # Universe

    # ---- DMP layer (523 bytes incl. 0x00 start-code + 512 channels)
    dmp = b""
    pdu_length_dmp = 0x7000 | (638 - 115)
    dmp += struct.pack(">H", pdu_length_dmp)
    dmp += struct.pack(">B", 0x02)            # vector DMP_SET_PROPERTY
    dmp += struct.pack(">B", 0xA1)            # Address+Data Type
    dmp += struct.pack(">H", 0x0000)          # First Property Address
    dmp += struct.pack(">H", 0x0001)          # Address Increment
    dmp += struct.pack(">H", 513)             # Property Value Count (513 incl start-code)
    dmp += struct.pack(">B", 0x00)            # DMX start-code
    dmp += dmx

    return root + framing + dmp


def sacn_multicast_address(universe: int) -> str:
    """sACN universes mapen naar multicast 239.255.<hi>.<lo>:5568."""
    universe = universe & 0xFFFF
    return f"239.255.{(universe >> 8) & 0xFF}.{universe & 0xFF}"


# ---- universe-state + cue handles ------------------------------------------

@dataclass
class _Universe:
    protocol: str   # "artnet" | "sacn"
    number: int
    host: str       # "" → broadcast (artnet) / multicast (sacn)
    port: int       # 6454 (artnet) / 5568 (sacn)
    buffer: bytearray = field(default_factory=lambda: bytearray(512))
    sequence: int = 0


@dataclass
class _CueHandle:
    cue_id: str
    universe_key: tuple[str, int]  # (protocol, universe)
    mode: str                       # "snapshot" | "fade" | "chase"
    target: dict[int, int] = field(default_factory=dict)
    fade_total_s: float = 0.0
    fade_started_at: float = 0.0
    fade_start_values: dict[int, int] = field(default_factory=dict)
    chase_steps: list[dict[int, int]] = field(default_factory=list)
    chase_step_time: float = 0.5
    chase_loops_total: int = 0       # 0 = oneindig
    chase_pingpong: bool = False
    chase_started_at: float = 0.0
    chase_loops_done: int = 0
    chase_finished: bool = False     # zet zichzelf op True als loops opraken


# ---- engine ---------------------------------------------------------------

class DmxEngine(QObject):
    """Beheert universe-buffers en pusht ze met de geconfigureerde
    refresh-rate via UDP. Cues registreren via ``play()``."""

    cue_finished = pyqtSignal(str)     # cue_id — gefired als chase z'n loops klaar heeft
    send_failed = pyqtSignal(str, str)  # cue_id, error voor UI-statusbar

    DEFAULT_REFRESH_HZ = 30
    MAX_REFRESH_HZ = 60
    MIN_REFRESH_HZ = 5

    def __init__(self, parent: QObject | None = None,
                 refresh_hz: int = DEFAULT_REFRESH_HZ):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._universes: dict[tuple[str, int], _Universe] = {}
        self._cues: dict[str, _CueHandle] = {}
        self._refresh_hz = max(self.MIN_REFRESH_HZ,
                               min(self.MAX_REFRESH_HZ, refresh_hz))
        self._sock: socket.socket | None = None
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str = ""

    @property
    def available(self) -> bool:
        return True  # pure-Python, geen optionele dep

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def refresh_hz(self) -> int:
        return self._refresh_hz

    @property
    def last_error(self) -> str:
        return self._last_error

    # ---- public API --------------------------------------------------------

    def start(self) -> tuple[bool, str]:
        if self.running:
            return True, ""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # multicast TTL voor sACN (1 = LAN-only)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        except Exception as e:
            self._last_error = str(e)
            return False, self._last_error
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._send_loop, name="dmx-sender", daemon=True,
        )
        self._thread.start()
        self._last_error = ""
        return True, ""

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def shutdown(self) -> None:
        with self._lock:
            self._cues.clear()
        self.stop()

    def set_refresh_hz(self, hz: int) -> None:
        self._refresh_hz = max(self.MIN_REFRESH_HZ,
                               min(self.MAX_REFRESH_HZ, int(hz)))

    def play(self, cue) -> tuple[bool, str]:
        """Start een DMX-cue. Verwacht een Cue-dataclass met de
        ``dmx_*``-velden. Snapshot past direct toe; fade ramp't via de
        sender-loop; chase doorloopt z'n stappen automatisch."""
        protocol = (cue.dmx_protocol or "artnet").lower()
        if protocol not in ("artnet", "sacn"):
            return False, f"Unknown DMX protocol: {protocol}"
        universe = int(cue.dmx_universe or 0)
        host = (cue.dmx_host or "").strip()
        port = int(cue.dmx_port) if cue.dmx_port else (
            ARTNET_PORT if protocol == "artnet" else SACN_PORT
        )
        if port <= 0 or port > 65535:
            return False, f"Port out of range: {port}"

        mode = (cue.dmx_mode or "snapshot").lower()
        if mode not in ("snapshot", "fade", "chase"):
            return False, f"Unknown DMX mode: {mode}"

        with self._lock:
            key = (protocol, universe)
            if key not in self._universes:
                self._universes[key] = _Universe(
                    protocol=protocol, number=universe,
                    host=host, port=port,
                )
            else:
                # Update routing als bestaande universe opnieuw geadresseerd
                # wordt (nieuwe target-host, andere port).
                if host:
                    self._universes[key].host = host
                if port:
                    self._universes[key].port = port

            # Stop een eventueel lopende handle voor dezelfde cue (re-fire).
            self._cues.pop(cue.id, None)

            if mode == "chase":
                steps = parse_chase_steps(cue.dmx_chase_steps)
                if not steps:
                    return False, "Chase has no steps"
                handle = _CueHandle(
                    cue_id=cue.id,
                    universe_key=key,
                    mode="chase",
                    target={},
                    chase_steps=steps,
                    chase_step_time=max(0.01, float(cue.dmx_step_time or 0.5)),
                    chase_loops_total=int(cue.dmx_chase_loops or 0),
                    chase_pingpong=bool(cue.dmx_chase_pingpong),
                    chase_started_at=time.monotonic(),
                )
                self._cues[cue.id] = handle
                # Pas meteen step 0 toe zodat de cue niet één tick op zwart staat.
                self._apply_values(self._universes[key].buffer, steps[0])
                return True, ""

            target = parse_dmx_values(cue.dmx_values)
            if not target:
                return False, "DMX cue has no values"

            if mode == "snapshot" or float(cue.dmx_fade_time or 0.0) <= 0:
                # Schrijf direct in de buffer (LTP overschrijft eerdere cues).
                self._apply_values(self._universes[key].buffer, target)
                # Snapshot heeft geen verdere lifecycle — geen handle nodig.
                # Maar we registreren 'm wel zodat de controller via
                # is_playing() kan polleren (en stop_cue() weer kan
                # terugschrijven indien gewenst).
                self._cues[cue.id] = _CueHandle(
                    cue_id=cue.id, universe_key=key, mode="snapshot",
                    target=target,
                )
                return True, ""

            # mode == "fade" met een fade_time > 0
            now = time.monotonic()
            buf = self._universes[key].buffer
            start_values = {ch: buf[ch - 1] for ch in target}
            handle = _CueHandle(
                cue_id=cue.id, universe_key=key, mode="fade",
                target=target,
                fade_total_s=float(cue.dmx_fade_time),
                fade_started_at=now,
                fade_start_values=start_values,
            )
            self._cues[cue.id] = handle
            return True, ""

    def stop_cue(self, cue_id: str) -> None:
        """Verwijder de cue-handle. Bij snapshot/fade laten we de huidige
        waardes in de universe-buffer staan — een lichttafel-feel: 'stop'
        betekent niet automatisch een blackout."""
        with self._lock:
            self._cues.pop(cue_id, None)

    def is_playing(self, cue_id: str) -> bool:
        """True voor snapshot/fade zolang we de handle bijhouden, en voor
        chase tot z'n loops opraken."""
        with self._lock:
            handle = self._cues.get(cue_id)
            if handle is None:
                return False
            if handle.mode == "chase":
                return not handle.chase_finished
            if handle.mode == "fade":
                return (time.monotonic() - handle.fade_started_at
                        < handle.fade_total_s)
            return True  # snapshot blijft "playing" tot expliciete stop

    def blackout(self) -> None:
        """Zet alle universes op 0. Handig voor een Stop-All paniek-knop
        die ook lichten meeneemt."""
        with self._lock:
            for u in self._universes.values():
                for i in range(512):
                    u.buffer[i] = 0
            self._cues.clear()

    # ---- internals ---------------------------------------------------------

    @staticmethod
    def _apply_values(buffer: bytearray, values: dict[int, int]) -> None:
        for ch, val in values.items():
            if 1 <= ch <= 512:
                buffer[ch - 1] = max(0, min(255, val))

    def _tick_fade(self, handle: _CueHandle, now: float, buffer: bytearray) -> bool:
        """Eén tick voor een lopende fade. Return True als nog actief."""
        elapsed = now - handle.fade_started_at
        if handle.fade_total_s <= 0 or elapsed >= handle.fade_total_s:
            self._apply_values(buffer, handle.target)
            return False
        progress = elapsed / handle.fade_total_s
        for ch, target_val in handle.target.items():
            start_val = handle.fade_start_values.get(ch, buffer[ch - 1])
            new_val = int(round(start_val + (target_val - start_val) * progress))
            buffer[ch - 1] = max(0, min(255, new_val))
        return True

    def _tick_chase(self, handle: _CueHandle, now: float, buffer: bytearray) -> bool:
        """Eén tick voor een lopende chase. Return True als nog actief."""
        if handle.chase_finished:
            return False
        n = len(handle.chase_steps)
        if n == 0:
            handle.chase_finished = True
            return False
        elapsed = now - handle.chase_started_at
        # Steps tellen van linker- of zigzag-volgorde.
        if handle.chase_pingpong:
            cycle_len = 2 * (n - 1) if n > 1 else 1
        else:
            cycle_len = n
        if cycle_len <= 0:
            cycle_len = 1
        cycle_period = handle.chase_step_time * cycle_len
        if cycle_period > 0:
            cycles_done = int(elapsed // cycle_period)
            cycle_phase = elapsed - cycles_done * cycle_period
        else:
            cycles_done = 0
            cycle_phase = 0
        # Eindigt na N loops? Als chase_loops_total = 0 → oneindig.
        if (handle.chase_loops_total > 0
                and cycles_done >= handle.chase_loops_total):
            # Pak laatste step zodat we niet met een random fragment eindigen.
            self._apply_values(buffer, handle.chase_steps[-1])
            handle.chase_finished = True
            self.cue_finished.emit(handle.cue_id)
            return False
        idx_in_cycle = int(cycle_phase // handle.chase_step_time)
        if handle.chase_pingpong and n > 1:
            if idx_in_cycle >= n:
                idx = 2 * (n - 1) - idx_in_cycle
            else:
                idx = idx_in_cycle
        else:
            idx = idx_in_cycle % n
        idx = max(0, min(n - 1, idx))
        self._apply_values(buffer, handle.chase_steps[idx])
        return True

    def _send_loop(self) -> None:
        period = 1.0 / float(self._refresh_hz)
        next_tick = time.monotonic()
        while not self._stop_evt.is_set():
            now = time.monotonic()
            with self._lock:
                # Update fades + chases voor lopende cues
                for handle in list(self._cues.values()):
                    universe = self._universes.get(handle.universe_key)
                    if universe is None:
                        continue
                    if handle.mode == "fade":
                        self._tick_fade(handle, now, universe.buffer)
                    elif handle.mode == "chase":
                        self._tick_chase(handle, now, universe.buffer)
                # Push iedere universe
                for u in self._universes.values():
                    try:
                        self._send_universe(u)
                    except Exception as e:
                        self._last_error = str(e)
                        # Niet fataal — show kan doorlopen, maar UI horen
                        self.send_failed.emit("", str(e))
            # Wacht tot volgende tick
            next_tick += period
            sleep_s = next_tick - time.monotonic()
            if sleep_s > 0:
                self._stop_evt.wait(timeout=sleep_s)
            else:
                # We liepen achter — reset zodat we niet eeuwig inhalen
                next_tick = time.monotonic()

    def _send_universe(self, universe: _Universe) -> None:
        if self._sock is None:
            return
        universe.sequence = (universe.sequence + 1) & 0xFF
        if universe.sequence == 0:
            universe.sequence = 1  # Art-Net spec: 0 = sequencing disabled
        if universe.protocol == "artnet":
            packet = encode_artnet_dmx(
                universe.number, universe.sequence, bytes(universe.buffer),
            )
            host = universe.host or "<broadcast>"
            self._sock.sendto(packet, (host, universe.port))
        else:  # sacn
            packet = encode_sacn_dmx(
                universe.number, universe.sequence, bytes(universe.buffer),
            )
            host = universe.host or sacn_multicast_address(universe.number)
            self._sock.sendto(packet, (host, universe.port))


# ---- status-registratie ----------------------------------------------------

def register_status(engine: DmxEngine | None = None) -> None:
    if engine is not None and engine.running:
        u_count = len(engine._universes)  # type: ignore[attr-defined]
        detail = (
            f"Streaming {u_count} universe(s) at {engine.refresh_hz} Hz"
            if u_count else f"Idle (refresh {engine.refresh_hz} Hz)"
        )
    elif engine is not None and engine.last_error:
        detail = f"Off — last error: {engine.last_error}"
    else:
        detail = "Off — Art-Net + sACN raw-UDP, no external dependency"
    register(EngineStatus(
        name="DMX (Art-Net + sACN)",
        available=True,
        detail=detail,
        short="dmx",
    ))
