"""Tests voor de showtime-lock toggle op de transport-widget.

We isoleren het widget zonder MainWindow zodat we het signal-gedrag,
de checked-state, en de label-flip kunnen verifiëren zonder de hele
app op te starten."""

from __future__ import annotations

from livefire.ui.transport import TransportWidget


def test_showtime_toggle_default_off(qt_app) -> None:
    tw = TransportWidget()
    assert tw.is_showtime() is False
    assert "🔓" in tw.btn_showtime.text() or "Showtime" in tw.btn_showtime.text()


def test_showtime_toggle_emits_signal(qt_app) -> None:
    tw = TransportWidget()
    received: list[bool] = []
    tw.showtime_toggled.connect(received.append)
    tw.btn_showtime.click()
    assert received == [True]
    assert tw.is_showtime() is True
    tw.btn_showtime.click()
    assert received == [True, False]
    assert tw.is_showtime() is False


def test_showtime_icon_flips_on_toggle(qt_app) -> None:
    tw = TransportWidget()
    icon_off = tw.btn_showtime.icon()
    tw.btn_showtime.setChecked(True)
    icon_on = tw.btn_showtime.icon()
    # cacheKey() vergelijkt het onderliggende QIcon — wisselt zodra we
    # naar de gesloten-slot-pixmap switchen. Andere test-omgevingen
    # kunnen de bestanden missen (icon=null); dan is deze assert
    # tolerant want isNull-isNull → gelijk, en we vallen naar 't
    # is_showtime-pad om de toggle wel te bevestigen.
    if not icon_off.isNull() and not icon_on.isNull():
        assert icon_off.cacheKey() != icon_on.cacheKey()
    assert tw.is_showtime() is True


def test_set_showtime_programmatic_no_double_emit(qt_app) -> None:
    """set_showtime mag geen redundant signal sturen als de state al klopt."""
    tw = TransportWidget()
    received: list[bool] = []
    tw.showtime_toggled.connect(received.append)
    tw.set_showtime(True)
    assert received == [True]
    tw.set_showtime(True)  # idempotent
    assert received == [True]
    tw.set_showtime(False)
    assert received == [True, False]
