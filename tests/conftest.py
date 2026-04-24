"""Gedeelde pytest-fixtures."""

from __future__ import annotations

import pytest

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qt_app():
    """Eén QApplication voor de hele testsessie — QObject/pyqtSignal werken
    alleen binnen een QApplication-context. Terug te gebruiken over meerdere
    tests heen (QApplication kan maar één keer bestaan per proces)."""
    app = QApplication.instance() or QApplication([])
    yield app
