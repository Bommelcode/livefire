"""Splash-pixmap builder. Hergebruikt door de opstart-splash en de
Help → Over-dialog zodat beide identieke styling tonen."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from .. import APP_NAME, APP_VERSION


_ICON_PATH = Path(__file__).parent.parent / "resources" / "icon.png"

SPLASH_W = 460
SPLASH_H = 520
SPLASH_ICON = 280


def build_splash_pixmap() -> QPixmap:
    """Splash-pixmap met icoon + appnaam + versie + ondertitel. Gebruikt
    dezelfde dark-theme kleuren als de hoofd-UI."""
    pm = QPixmap(SPLASH_W, SPLASH_H)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Card-achtergrond
    p.setBrush(QColor("#1e1e1e"))
    p.setPen(QPen(QColor("#3a3a3a"), 1))
    p.drawRoundedRect(0, 0, SPLASH_W - 1, SPLASH_H - 1, 16, 16)
    # Icoon centraal bovenaan
    if _ICON_PATH.is_file():
        icon = QPixmap(str(_ICON_PATH)).scaled(
            SPLASH_ICON, SPLASH_ICON,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        p.drawPixmap((SPLASH_W - icon.width()) // 2, 40, icon)
    # Appnaam
    p.setPen(QColor("#e0e0e0"))
    font = QFont("Segoe UI", 26, QFont.Weight.Bold)
    p.setFont(font)
    p.drawText(QRect(0, 340, SPLASH_W, 44),
               Qt.AlignmentFlag.AlignCenter, APP_NAME)
    # Versie
    font.setPointSize(11)
    font.setBold(False)
    p.setFont(font)
    p.setPen(QColor("#3aa2e6"))
    p.drawText(QRect(0, 388, SPLASH_W, 20),
               Qt.AlignmentFlag.AlignCenter, f"versie {APP_VERSION}")
    # Subtitel
    font.setPointSize(9)
    p.setFont(font)
    p.setPen(QColor("#9a9a9a"))
    p.drawText(QRect(0, 430, SPLASH_W, 16),
               Qt.AlignmentFlag.AlignCenter,
               "Cue-based playback voor live events")
    p.end()
    return pm
