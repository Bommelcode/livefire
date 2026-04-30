"""Dark-theme stylesheet en kleurconstanten."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPolygonF


# ---- palette ---------------------------------------------------------------

BG_DARK = "#1e1e1e"
BG_MID = "#2a2a2a"
BG_LIGHT = "#333333"
TEXT = "#e0e0e0"
TEXT_DIM = "#9a9a9a"
ACCENT = "#3aa2e6"   # liveFire-blauw
ACCENT_ALT = "#e6a23a"
OK = "#5cb85c"
WARN = "#f0ad4e"
ERR = "#d9534f"
SEL_BG = "#0d4c74"
BORDER = "#3a3a3a"


STATE_COLORS = {
    "idle": QColor("#9a9a9a"),
    "running": QColor(ACCENT),
    "finished": QColor(OK),
}


# QLab-geïnspireerde cue-kleuren, afgestemd op ons donkere thema.
# (label, hex). Volgorde bepaalt de dropdown in de inspector.
CUE_COLORS: list[tuple[str, str]] = [
    ("Geen",    ""),
    ("Rood",    "#c0392b"),
    ("Oranje",  "#d35400"),
    ("Geel",    "#c9a227"),
    ("Groen",   "#2e8b57"),
    ("Cyaan",   "#2aa198"),
    ("Blauw",   "#2980b9"),
    ("Paars",   "#7d3c98"),
    ("Roze",    "#c71585"),
    ("Grijs",   "#606060"),
]


def tint_for_row(hex_color: str, alpha: int = 110) -> QColor:
    """Geef een semi-transparante variant van hex_color terug voor row-backgrounds.
    Donker thema: alpha ~110/255 geeft duidelijk zichtbaar maar niet schreeuwend."""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def _make_arrow_pixmap(direction: str, color: str = TEXT) -> str:
    """Teken een 9×9 driehoek-pixmap en schrijf naar tempdir. Retourneert het
    pad met forward-slashes zodat het veilig in een Qt-stylesheet url() past.
    Qt accepteert geen border-triangle-truc voor ::up-arrow/::down-arrow; een
    image: url() is wel betrouwbaar."""
    size = 9
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    if direction == "up":
        poly = QPolygonF([QPointF(1, 7), QPointF(size - 1, 7), QPointF(size / 2, 2)])
    else:
        poly = QPolygonF([QPointF(1, 2), QPointF(size - 1, 2), QPointF(size / 2, 7)])
    p.drawPolygon(poly)
    p.end()
    out = Path(tempfile.gettempdir()) / f"livefire_arrow_{direction}.png"
    pm.save(str(out), "PNG")
    return str(out).replace("\\", "/")


def build_stylesheet() -> str:
    """Genereer de stylesheet. Moet ná QApplication()-init worden aangeroepen
    omdat QPixmap een GUI-context nodig heeft voor arrow-icons."""
    arrow_up = _make_arrow_pixmap("up")
    arrow_down = _make_arrow_pixmap("down")
    return _STYLESHEET_TEMPLATE.format(
        BG_DARK=BG_DARK, BG_MID=BG_MID, BG_LIGHT=BG_LIGHT,
        TEXT=TEXT, TEXT_DIM=TEXT_DIM, ACCENT=ACCENT,
        OK=OK, ERR=ERR, SEL_BG=SEL_BG, BORDER=BORDER,
        ARROW_UP=arrow_up, ARROW_DOWN=arrow_down,
    )


_STYLESHEET_TEMPLATE = """
QMainWindow, QWidget {{
    background-color: {BG_DARK};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}

QToolBar {{
    background: {BG_MID};
    border: none;
    spacing: 6px;
    padding: 4px;
}}

QStatusBar {{
    background: {BG_MID};
    color: {TEXT_DIM};
}}

QTreeWidget, QListWidget {{
    background: {BG_MID};
    alternate-background-color: #252525;
    border: 1px solid {BORDER};
    selection-background-color: {SEL_BG};
    selection-color: {TEXT};
}}

QTreeWidget::item {{
    padding: 4px 6px;
    border-bottom: 1px solid #242424;
}}

QTreeWidget::item:selected {{
    background: {SEL_BG};
    color: {TEXT};
}}

QTreeWidget::item:selected:!active {{
    background: {SEL_BG};
    color: {TEXT};
}}

QHeaderView::section {{
    background: {BG_LIGHT};
    color: {TEXT_DIM};
    padding: 4px 8px;
    border: none;
    border-right: 1px solid {BORDER};
}}

QPushButton {{
    background: {BG_LIGHT};
    border: 1px solid {BORDER};
    padding: 6px 14px;
    border-radius: 4px;
    color: {TEXT};
}}

QPushButton:hover {{ background: #3d3d3d; }}
QPushButton:pressed {{ background: {SEL_BG}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; }}

QPushButton#goButton {{
    background: {OK};
    color: white;
    font-weight: bold;
    min-width: 90px;
    min-height: 32px;
    font-size: 11pt;
}}
QPushButton#goButton:hover {{ background: #4ca44c; }}

QPushButton#stopButton {{
    background: {ERR};
    color: white;
    font-weight: bold;
    min-height: 32px;
}}
QPushButton#stopButton:hover {{ background: #c04a46; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {BG_MID};
    border: 1px solid {BORDER};
    padding: 4px 6px;
    color: {TEXT};
    min-height: 22px;
    border-radius: 3px;
}}

QComboBox::drop-down {{ border: none; }}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}

/* Spinbox up/down knoppen. In Qt-stylesheet-mode tekent Qt géén native
   pijl-glyph meer — we bouwen de driehoek zelf met border-triangles. */
QSpinBox, QDoubleSpinBox {{
    padding-right: 18px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 16px;
    background: {BG_LIGHT};
    border-left: 1px solid {BORDER};
    border-top-right-radius: 3px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 16px;
    background: {BG_LIGHT};
    border-left: 1px solid {BORDER};
    border-top: 1px solid {BORDER};
    border-bottom-right-radius: 3px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: #3d3d3d;
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {SEL_BG};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({ARROW_UP});
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({ARROW_DOWN});
    width: 9px;
    height: 9px;
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 10px;
    color: {TEXT_DIM};
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}

QSplitter::handle {{ background: {BORDER}; }}

QScrollBar:vertical {{
    background: {BG_DARK};
    width: 12px;
}}
QScrollBar::handle:vertical {{
    background: {BG_LIGHT};
    min-height: 30px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{ background: #4a4a4a; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QMenu {{
    background: {BG_MID};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{ background: {SEL_BG}; }}

QMenuBar {{
    background: {BG_MID};
    color: {TEXT};
}}
QMenuBar::item:selected {{ background: {SEL_BG}; }}
"""
