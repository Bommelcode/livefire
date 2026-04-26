"""Tests voor het licensing-systeem (HMAC-based offline keys).

Verifieert key-format roundtrip, expiration-detection, has_feature()
gating per cue-type, en activate/deactivate state-changes."""

from __future__ import annotations

from datetime import date, timedelta

import pytest


def test_generate_and_parse_roundtrip() -> None:
    from livefire.licensing import generate_key, parse_key, LicenseTier
    exp = date.today() + timedelta(days=30)
    key = generate_key(LicenseTier.MONTH, exp)
    assert key.startswith("LF-MONTH-")
    parsed = parse_key(key)
    assert parsed is not None
    assert parsed.tier == "MONTH"
    assert parsed.expires == exp
    assert not parsed.expired


def test_generate_unknown_tier_raises() -> None:
    from livefire.licensing import generate_key
    with pytest.raises(ValueError):
        generate_key("WEEK", date.today())


def test_parse_rejects_bad_format() -> None:
    from livefire.licensing import parse_key
    assert parse_key("") is None
    assert parse_key("garbage") is None
    assert parse_key("LF-MONTH-2026-12-31") is None  # mist HMAC
    assert parse_key("LF-WEEK-2026-12-31-12345678") is None  # ongeldige tier


def test_parse_rejects_tampered_hmac() -> None:
    from livefire.licensing import generate_key, parse_key, LicenseTier
    key = generate_key(LicenseTier.YEAR, date.today() + timedelta(days=10))
    # Wijzig de HMAC-tail
    if key[-1] == "0":
        bad = key[:-1] + "1"
    else:
        bad = key[:-1] + "0"
    assert parse_key(bad) is None


def test_parse_rejects_tampered_date() -> None:
    """Een aangepaste einddatum moet niet meer matchen op de HMAC."""
    from livefire.licensing import generate_key, parse_key, LicenseTier
    key = generate_key(LicenseTier.DAY, date(2026, 1, 1))
    # Vervang de datum maar laat de oorspronkelijke HMAC staan
    bad = key.replace("2026-01-01", "2099-12-31")
    assert parse_key(bad) is None


def test_parsed_expired_flag() -> None:
    from livefire.licensing import generate_key, parse_key, LicenseTier
    past = date.today() - timedelta(days=1)
    key = generate_key(LicenseTier.DAY, past)
    parsed = parse_key(key)
    assert parsed is not None
    assert parsed.expired


def test_has_feature_free_blocks_paid_types(free_license) -> None:
    """In FREE-tier mogen alleen audio + organisatorische cues."""
    from livefire import licensing
    from livefire.cues import CueType
    assert licensing.has_feature(CueType.AUDIO) is True
    assert licensing.has_feature(CueType.WAIT) is True
    assert licensing.has_feature(CueType.STOP) is True
    assert licensing.has_feature(CueType.FADE) is True
    assert licensing.has_feature(CueType.START) is True
    assert licensing.has_feature(CueType.GROUP) is True
    assert licensing.has_feature(CueType.MEMO) is True
    # Paid types moeten geblokkeerd zijn
    assert licensing.has_feature(CueType.VIDEO) is False
    assert licensing.has_feature(CueType.IMAGE) is False
    assert licensing.has_feature(CueType.PRESENTATION) is False
    assert licensing.has_feature(CueType.NETWORK) is False


def test_has_feature_pro_unlocks_all(pro_license) -> None:
    from livefire import licensing
    from livefire.cues import CueType
    for ct in CueType.ALL:
        assert licensing.has_feature(ct) is True, f"{ct} moet vrij zijn voor Pro"


def test_current_tier_and_is_pro_free(free_license) -> None:
    from livefire import licensing
    assert licensing.current_tier() == licensing.LicenseTier.FREE
    assert licensing.is_pro() is False
    assert licensing.expires_at() is None
    assert licensing.days_remaining() is None


def test_current_tier_and_is_pro_with_license(pro_license) -> None:
    from livefire import licensing
    assert licensing.current_tier() == licensing.LicenseTier.YEAR
    assert licensing.is_pro() is True
    assert licensing.expires_at() is not None
    assert licensing.days_remaining() is not None
    assert licensing.days_remaining() > 0


def test_status_summary_free_and_pro(qt_app) -> None:
    """Zet beide states expliciet en check de teksten."""
    from livefire import licensing
    saved = licensing._parsed
    try:
        licensing._parsed = None
        s = licensing.status_summary()
        assert "Gratis" in s
        licensing._parsed = licensing.ParsedKey(
            tier=licensing.LicenseTier.MONTH,
            expires=date.today() + timedelta(days=15),
            raw="x",
        )
        s = licensing.status_summary()
        assert "Pro" in s
        assert "MONTH" in s
        assert "15 dagen" in s
    finally:
        licensing._parsed = saved


def test_activate_invalid_key_returns_error(qt_app, free_license) -> None:
    from livefire import licensing
    ok, msg = licensing.activate("not-a-real-key")
    assert ok is False
    assert "Ongeldig" in msg or "ongeldig" in msg.lower()
    assert licensing.is_pro() is False


def test_activate_expired_key_returns_error(qt_app, free_license) -> None:
    from livefire import licensing
    expired = licensing.generate_key(
        licensing.LicenseTier.DAY,
        date.today() - timedelta(days=10),
    )
    ok, msg = licensing.activate(expired)
    assert ok is False
    assert "verlopen" in msg.lower()
    assert licensing.is_pro() is False


def test_paid_cue_type_set_matches_expectation() -> None:
    """De set met Pro-only cue-types is een vast contract — als die
    verandert dwingt deze test je het te updaten in CHANGELOG."""
    from livefire.licensing import PAID_CUE_TYPES
    from livefire.cues import CueType
    expected = {CueType.VIDEO, CueType.IMAGE, CueType.PRESENTATION, CueType.NETWORK}
    assert set(PAID_CUE_TYPES) == expected


def test_prices_match_announced_pricing() -> None:
    """Prijzen moeten overeenkomen met wat gepubliceerd staat. Als deze
    wijzigen: README, CHANGELOG en site moeten ook bij."""
    from livefire.licensing import PRICES_EUR, LicenseTier
    assert PRICES_EUR[LicenseTier.DAY] == 4.95
    assert PRICES_EUR[LicenseTier.MONTH] == 13.95
    assert PRICES_EUR[LicenseTier.YEAR] == 139.95
    assert PRICES_EUR[LicenseTier.LIFETIME] == 249.95


def test_lifetime_key_roundtrip(qt_app) -> None:
    """LIFETIME-keys gebruiken date(9999,12,31) als sentinel-einddatum
    en werken via dezelfde HMAC-flow als de termijn-tiers."""
    from livefire import licensing
    saved = licensing._parsed
    try:
        key = licensing.generate_lifetime_key()
        assert key.startswith("LF-LIFETIME-9999-12-31-")
        ok, msg = licensing.activate(key)
        assert ok, msg
        assert licensing.is_pro()
        assert licensing.current_tier() == licensing.LicenseTier.LIFETIME
        # Lifetime heeft geen einddatum-countdown
        assert licensing.days_remaining() is None
        # Status-tekst moet 'Lifetime' zonder dagen-resterend bevatten
        s = licensing.status_summary()
        assert "Lifetime" in s
        assert "geen einddatum" in s.lower()
        assert "dagen resterend" not in s
        # Alle paid cue-types unlocked
        from livefire.cues import CueType
        for ct in CueType.ALL:
            assert licensing.has_feature(ct)
    finally:
        licensing._parsed = saved


def test_lifetime_key_via_explicit_generate_key() -> None:
    """``generate_lifetime_key()`` is een alias voor
    ``generate_key(LIFETIME, LIFETIME_END_DATE)`` — beide moeten dezelfde
    key produceren."""
    from livefire import licensing
    a = licensing.generate_lifetime_key()
    b = licensing.generate_key(
        licensing.LicenseTier.LIFETIME,
        licensing.LIFETIME_END_DATE,
    )
    assert a == b


def test_controller_blocks_paid_cue_in_free_tier(qt_app, free_license) -> None:
    """In FREE-tier moet een paid cue (bv. Network) NIET de engine
    raken; het cue_blocked_by_license signal moet fire'n."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from livefire.workspace import Workspace
    from livefire.cues import Cue, CueType
    from livefire.playback import PlaybackController

    ws = Workspace()
    cue = Cue(
        cue_type=CueType.NETWORK, cue_number="1", name="OSC trigger",
        network_address="/test/x",
    )
    ws.add_cue(cue)
    ctrl = PlaybackController(ws)
    blocked: list = []
    ctrl.cue_blocked_by_license.connect(
        lambda cid, ct: blocked.append((cid, ct))
    )
    try:
        ctrl.fire_cue(cue.id)
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()
        assert len(blocked) == 1
        assert blocked[0] == (cue.id, CueType.NETWORK)
    finally:
        ctrl.shutdown()


def test_controller_allows_audio_cue_in_free_tier(qt_app, free_license, tmp_path) -> None:
    """Audio is altijd gratis — moet ook in FREE-tier draaien."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from livefire.workspace import Workspace
    from livefire.cues import Cue, CueType
    from livefire.playback import PlaybackController

    ws = Workspace()
    # Geen file_path: audio.play_file faalt schoon, geen blokkade-signal.
    cue = Cue(cue_type=CueType.AUDIO, cue_number="1", name="Empty audio")
    ws.add_cue(cue)
    ctrl = PlaybackController(ws)
    blocked: list = []
    ctrl.cue_blocked_by_license.connect(
        lambda cid, ct: blocked.append((cid, ct))
    )
    try:
        ctrl.fire_cue(cue.id)
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()
        assert blocked == [], "Audio moet niet geblokkeerd worden"
    finally:
        ctrl.shutdown()
