"""Gedeelde pytest-fixtures."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qt_app():
    """Eén QApplication voor de hele testsessie — QObject/pyqtSignal werken
    alleen binnen een QApplication-context. Terug te gebruiken over meerdere
    tests heen (QApplication kan maar één keer bestaan per proces)."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def pro_license():
    """Geeft tijdelijk een Pro-licentie aan de licensing-module zodat
    tests met paid cue-types (Video / Image / Presentation / Network)
    door de license-gate komen. In-memory only — raakt QSettings niet."""
    from livefire import licensing
    saved = licensing._parsed
    licensing._parsed = licensing.ParsedKey(
        tier=licensing.LicenseTier.YEAR,
        expires=date.today() + timedelta(days=365),
        raw="test-license",
    )
    yield
    licensing._parsed = saved


@pytest.fixture
def free_license():
    """Garandeert FREE-tier voor de test (geen Pro). Expliciet zetten in
    plaats van leunen op default zodat een vorige test geen state lekt."""
    from livefire import licensing
    saved = licensing._parsed
    licensing._parsed = None
    yield
    licensing._parsed = saved
