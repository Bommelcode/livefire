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


def test_showtime_label_flips_on_toggle(qt_app) -> None:
    tw = TransportWidget()
    locked_text_before = tw.btn_showtime.text()
    tw.btn_showtime.setChecked(True)
    locked_text_after = tw.btn_showtime.text()
    assert locked_text_before != locked_text_after
    # Visuele indicator: 🔒 wanneer aan, 🔓 wanneer uit.
    assert "🔒" in locked_text_after


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
