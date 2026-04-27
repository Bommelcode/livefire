"""Licensing voor liveFire — freemium model.

* **Gratis tier**: Audio + organisatorische cues (Wait/Stop/Fade/Start/
  Group/Memo). Een complete audio-only show kun je daarmee bouwen.
* **Pro tier**: Video, Afbeelding, Presentatie, Network (OSC-out). Drie
  termijnen — dag, maand, jaar — gekoppeld aan een einddatum.

Module-level API
----------------
``init()`` laadt de actieve key uit QSettings. ``has_feature(cue_type)``
geeft `True/False` voor de enforcement-call sites (controller bij GO,
inspector bij selectie, drop-handler bij file-import).

``activate(key)`` en ``deactivate()`` bewaren wijzigingen direct op
disk en emit'en ``signaler.license_changed`` zodat UI-elementen mee
veranderen.

Key-format
----------
``LF-<TIER>-<YYYY-MM-DD>-<HMAC8>``

Validatie is volledig lokaal: HMAC-SHA256 over ``"<TIER>|<YYYY-MM-DD>"``,
eerste 8 hex-tekens. Hardcoded ``_SIGNING_SECRET`` hieronder — bewust
acceptabel voor een v1-launch met een kleine markt; voor wie een binary
kraakt: in een latere release kan Sil overstappen op JWT + server-
validatie zonder breaking changes voor bestaande keys.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from . import SETTINGS_ORG, SETTINGS_APP
from .cues import CueType


# ---- Feature-flag ----------------------------------------------------------

# Master-switch voor het hele freemium/licensing-systeem. Staat tijdelijk uit
# zodat alle cue-types vrij bruikbaar zijn en de Licentie-UI niet zichtbaar
# is. De volledige module blijft intact — flip terug naar ``True`` om de
# enforcement, banners en het menu-item Help → Licentie… weer aan te zetten.
LICENSING_ENABLED: Final[bool] = False


# ---- Tiers + prijzen + feature-mapping -------------------------------------

class LicenseTier:
    """Plain-class string-constants — direct in QSettings opslaanbaar."""

    FREE = "FREE"
    DAY = "DAY"
    MONTH = "MONTH"
    YEAR = "YEAR"
    LIFETIME = "LIFETIME"

    PRO_TIERS = (DAY, MONTH, YEAR, LIFETIME)


PRICES_EUR: Final[dict[str, float]] = {
    LicenseTier.DAY:       4.95,
    LicenseTier.MONTH:    13.95,
    LicenseTier.YEAR:    139.95,
    LicenseTier.LIFETIME: 249.95,
}

# Hoe lang een tier geldig is. LIFETIME staat hier bewust niet in —
# heeft geen termijn (zie ``LIFETIME_END_DATE`` voor de sentinel-
# einddatum die in keys wordt gezet).
DURATIONS: Final[dict[str, timedelta]] = {
    LicenseTier.DAY:   timedelta(days=1),
    LicenseTier.MONTH: timedelta(days=30),
    LicenseTier.YEAR:  timedelta(days=365),
}

# Sentinel-einddatum voor LIFETIME-keys. Python ondersteunt date tot
# 9999-12-31; we gebruiken die maximumwaarde zodat de bestaande HMAC-
# en parse-logica ongewijzigd blijft werken.
LIFETIME_END_DATE: Final[date] = date(9999, 12, 31)

# Welke cue-types vergrendeld zijn achter een Pro-tier. Audio en de
# organisatorische types blijven gratis.
PAID_CUE_TYPES: Final[frozenset[str]] = frozenset({
    CueType.VIDEO,
    CueType.IMAGE,
    CueType.PRESENTATION,
    CueType.NETWORK,
})

# URL waar de gebruiker een licentie kan kopen. Sil kan deze constant
# wijzigen voordat hij distributies bouwt om naar z'n eigen Stripe
# Checkout-pagina te verwijzen.
PURCHASE_URL = "https://livefire.app/buy"


# ---- HMAC-validatie + key-format -------------------------------------------

_SIGNING_SECRET: Final[bytes] = (
    b"livefire-v1-offline-license-secret-rotate-before-public-release"
)

_KEY_RE = re.compile(
    r"^LF-(DAY|MONTH|YEAR|LIFETIME)-(\d{4}-\d{2}-\d{2})-([0-9a-fA-F]{8})$"
)


def _expected_hmac(tier: str, expires: str) -> str:
    msg = f"{tier}|{expires}".encode("utf-8")
    return hmac.new(_SIGNING_SECRET, msg, hashlib.sha256).hexdigest()[:8]


def generate_key(tier: str, expires: date) -> str:
    """Genereer een geldige licentiekey. Sil's eigen tooling roept dit aan
    om keys uit te delen aan klanten — niet bereikbaar vanuit de UI."""
    if tier not in LicenseTier.PRO_TIERS:
        raise ValueError(f"Onbekende tier: {tier}")
    exp = expires.isoformat()
    sig = _expected_hmac(tier, exp)
    return f"LF-{tier}-{exp}-{sig}"


def generate_lifetime_key() -> str:
    """Convenience: genereer een LIFETIME-key met de sentinel-einddatum
    (9999-12-31). Equivalent aan
    ``generate_key(LicenseTier.LIFETIME, LIFETIME_END_DATE)``."""
    return generate_key(LicenseTier.LIFETIME, LIFETIME_END_DATE)


@dataclass(frozen=True)
class ParsedKey:
    tier: str
    expires: date
    raw: str

    @property
    def expired(self) -> bool:
        return date.today() > self.expires


def parse_key(key: str) -> ParsedKey | None:
    """Parse en valideer. Returns ``None`` bij ongeldige HMAC, formaatfout,
    of een onleesbare datum. Verlopen keys parsen wel succesvol; gebruik
    ``parsed.expired`` om te checken."""
    if not key:
        return None
    m = _KEY_RE.match(key.strip())
    if not m:
        return None
    tier, exp_str, sig = m.group(1), m.group(2), m.group(3).lower()
    if hmac.compare_digest(sig, _expected_hmac(tier, exp_str)):
        try:
            exp = date.fromisoformat(exp_str)
        except ValueError:
            return None
        return ParsedKey(tier=tier, expires=exp, raw=key.strip())
    return None


# ---- Module-state + signal -------------------------------------------------

_SETTING_KEY = "license/key"
_parsed: ParsedKey | None = None


class _Signaler(QObject):
    """Houder voor het ``license_changed``-signal. Module-level state
    heeft een Qt-host nodig om signals te kunnen emit'en."""
    license_changed = pyqtSignal()


# Eén singleton waar UI-componenten op kunnen connecten.
signaler = _Signaler()


def init() -> None:
    """Laad de huidige licentie uit QSettings. Roep dit éénmaal aan bij
    app-start vóórdat andere code ``has_feature()`` of ``current_tier()``
    gebruikt."""
    global _parsed
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    stored = settings.value(_SETTING_KEY, "", type=str)
    _parsed = parse_key(stored) if stored else None


# ---- Public lookup-functies ------------------------------------------------

def current_tier() -> str:
    if not LICENSING_ENABLED:
        return LicenseTier.LIFETIME
    if _parsed is None or _parsed.expired:
        return LicenseTier.FREE
    return _parsed.tier


def is_pro() -> bool:
    if not LICENSING_ENABLED:
        return True
    return current_tier() in LicenseTier.PRO_TIERS


def expires_at() -> date | None:
    return _parsed.expires if _parsed is not None else None


def days_remaining() -> int | None:
    """Resterende dagen voor een termijn-licentie. ``None`` voor FREE
    (geen licentie) en voor LIFETIME (geen einddatum)."""
    if _parsed is None or _parsed.expired:
        return None
    if _parsed.tier == LicenseTier.LIFETIME:
        return None
    return max(0, (_parsed.expires - date.today()).days)


def has_feature(cue_type: str) -> bool:
    """Of een cue van dit type bij GO en bij creatie mag draaien."""
    if not LICENSING_ENABLED:
        return True
    if cue_type not in PAID_CUE_TYPES:
        return True
    return is_pro()


def status_summary() -> str:
    """One-liner voor in de licentie-dialog en de about-pagina."""
    tier = current_tier()
    if tier == LicenseTier.FREE:
        return "Gratis — Audio + organisatorische cues"
    if tier == LicenseTier.LIFETIME:
        return "Pro (Lifetime) — geen einddatum"
    days = days_remaining() or 0
    exp = _parsed.expires.isoformat() if _parsed else "?"
    return f"Pro ({tier}) — geldig t/m {exp} ({days} dagen resterend)"


# ---- Mutators --------------------------------------------------------------

def activate(key: str) -> tuple[bool, str]:
    """Probeer ``key`` te activeren. Retourneert ``(ok, message)`` —
    bij succes wordt de key persistent opgeslagen en wordt
    ``signaler.license_changed`` geëmit."""
    global _parsed
    parsed = parse_key(key)
    if parsed is None:
        return False, (
            "Ongeldige licentiekey — controleer of je 'm volledig hebt geplakt."
        )
    if parsed.expired:
        return False, f"Deze key is verlopen op {parsed.expires.isoformat()}."
    _parsed = parsed
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    settings.setValue(_SETTING_KEY, parsed.raw)
    settings.sync()
    signaler.license_changed.emit()
    return True, f"Activatie gelukt — Pro tot en met {parsed.expires.isoformat()}."


def deactivate() -> None:
    """Verwijder de huidige licentie (zet terug naar FREE-tier)."""
    global _parsed
    _parsed = None
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    settings.remove(_SETTING_KEY)
    settings.sync()
    signaler.license_changed.emit()
