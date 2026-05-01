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


# ---- themes ----------------------------------------------------------------
#
# Elke theme is 'n palette + font-family + extra CSS-regels. De default-
# theme is wat module-level constants ook hebben (zodat consumers die
# `from .style import ACCENT` doen blijven werken). Andere themes
# wisselen alleen de QApplication-stylesheet — kleine details die
# hardcoded zijn op de default-constants overleven 'n theme-wissel
# tot de volgende app-start.
#
THEMES: dict[str, dict] = {
    "default": {
        "label": "liveFire (Default)",
        "font": '"Segoe UI", "Segoe UI Variable", "Tahoma", sans-serif',
        "palette": {
            "BG_DARK": "#1e1e1e", "BG_MID": "#2a2a2a", "BG_LIGHT": "#333333",
            "TEXT": "#e0e0e0", "TEXT_DIM": "#9a9a9a",
            "ACCENT": "#3aa2e6", "ACCENT_ALT": "#e6a23a",
            "OK": "#5cb85c", "ERR": "#d9534f",
            "SEL_BG": "#0d4c74", "BORDER": "#3a3a3a",
        },
        "extra": "",
    },
    "studio": {
        "label": "Studio Console (broadcast amber)",
        "font": '"Segoe UI", "Tahoma", sans-serif',
        "palette": {
            "BG_DARK": "#1a1d21", "BG_MID": "#22262b", "BG_LIGHT": "#2c3138",
            "TEXT": "#e6e6e6", "TEXT_DIM": "#7a8089",
            "ACCENT": "#f5a623", "ACCENT_ALT": "#39d353",
            "OK": "#39d353", "ERR": "#e74c3c",
            "SEL_BG": "#5a3d10", "BORDER": "#3d4248",
        },
        "extra": """
            QPushButton#goButton, QPushButton#stopButton {
                border: 2px solid #3d4248;
                border-radius: 2px;
                font-weight: bold;
            }
            QPushButton { border-radius: 2px; }
        """,
    },
    "linear": {
        "label": "Linear Modern (minimal violet)",
        "font": '"Inter", "Segoe UI", sans-serif',
        "palette": {
            "BG_DARK": "#0a0a0a", "BG_MID": "#161616", "BG_LIGHT": "#1f1f1f",
            "TEXT": "#e8e8e8", "TEXT_DIM": "#6a6a6a",
            "ACCENT": "#5e6ad2", "ACCENT_ALT": "#b8b8b8",
            "OK": "#5e6ad2", "ERR": "#eb5757",
            "SEL_BG": "#22243b", "BORDER": "#1f1f1f",
        },
        "extra": """
            QPushButton {
                border-radius: 6px;
                padding: 6px 12px;
                background: transparent;
                border: 1px solid #1f1f1f;
            }
            QPushButton:hover { background: #161616; }
            QGroupBox { border: 1px solid #1f1f1f; border-radius: 8px; }
            QTreeWidget { border: none; alternate-background-color: #0d0d0d; }
        """,
    },
    "qlab": {
        "label": "QLab Native (familiar orange)",
        "font": '"Segoe UI", "SF Pro Display", "Tahoma", sans-serif',
        "palette": {
            "BG_DARK": "#1e1e22", "BG_MID": "#27272d", "BG_LIGHT": "#32323a",
            "TEXT": "#f0f0f0", "TEXT_DIM": "#909096",
            "ACCENT": "#ff8c00", "ACCENT_ALT": "#ffaa3d",
            "OK": "#4cd964", "ERR": "#ff453a",
            "SEL_BG": "#7a3d00", "BORDER": "#3d3d44",
        },
        "extra": """
            QPushButton { border-radius: 5px; }
            QTreeWidget::item { border-bottom: 1px solid #2a2a30; }
        """,
    },
    "cinematic": {
        "label": "Cinematic (deep purple + gold)",
        "font": '"Segoe UI", "DM Sans", "Tahoma", sans-serif',
        "palette": {
            "BG_DARK": "#0d0a14", "BG_MID": "#1a1424", "BG_LIGHT": "#251c33",
            "TEXT": "#f0e8d8", "TEXT_DIM": "#8a7a98",
            "ACCENT": "#d4af37", "ACCENT_ALT": "#b87333",
            "OK": "#5cb85c", "ERR": "#c0392b",
            "SEL_BG": "#3d2855", "BORDER": "#2a1f3a",
        },
        "extra": """
            QPushButton {
                border-radius: 4px;
                font-weight: 600;
            }
            QPushButton#goButton {
                border: 2px solid #d4af37;
            }
            QGroupBox::title { color: #d4af37; }
        """,
    },
    "glass": {
        "label": "Glassmorphic (cyan glow)",
        "font": '"Segoe UI", "SF Pro Display", sans-serif',
        "palette": {
            "BG_DARK": "#13162e", "BG_MID": "#1a1d3a", "BG_LIGHT": "#252849",
            "TEXT": "#e6e8f5", "TEXT_DIM": "#7d8197",
            "ACCENT": "#7df9ff", "ACCENT_ALT": "#a78bfa",
            "OK": "#4ade80", "ERR": "#f87171",
            "SEL_BG": "#1f2960", "BORDER": "#2a2e54",
        },
        "extra": """
            QPushButton {
                border-radius: 12px;
                padding: 8px 14px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid #7df9ff;
            }
            QGroupBox {
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.02);
            }
            QTreeWidget {
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 12px;
            }
        """,
    },
}


# Per-theme layout-varianten. Een variant beschrijft de structurele
# rangschikking van GO/Stop/Showtime/Names/Timers in de transport-bar.
# TransportWidget leest theme + variant uit QSettings en construeert
# de bijpassende layout. Zie transport.py voor de daadwerkelijke
# implementaties.
LAYOUT_VARIANTS: dict[str, list[tuple[str, str]]] = {
    "default": [
        ("a", "A — Compact (default)"),
        ("b", "B — Single row"),
        ("c", "C — Centered timer"),
    ],
    "studio": [
        ("a", "A — Beveled frame"),
        ("b", "B — Dashboard split"),
        ("c", "C — Console row"),
    ],
    "linear": [
        ("a", "A — Stripped (default)"),
        ("b", "B — Inline minimal"),
        ("c", "C — Card centered"),
    ],
    "qlab": [
        ("a", "A — Hero countdown"),
        ("b", "B — Sidebar timer"),
        ("c", "C — Strip"),
    ],
    "cinematic": [
        ("a", "A — Hero countdown"),
        ("b", "B — Two-tier (big now-playing)"),
        ("c", "C — Theatre poster"),
    ],
    "glass": [
        ("a", "A — Card cluster (default)"),
        ("b", "B — Bento grid"),
        ("c", "C — Centered timer"),
    ],
}


def build_stylesheet(theme_id: str = "default") -> str:
    """Genereer de stylesheet voor de gegeven theme. Moet ná
    QApplication()-init worden aangeroepen omdat QPixmap een GUI-context
    nodig heeft voor arrow-icons."""
    theme = THEMES.get(theme_id) or THEMES["default"]
    pal = theme["palette"]
    font = theme["font"]
    extra = theme["extra"]
    arrow_up = _make_arrow_pixmap("up", pal["TEXT"])
    arrow_down = _make_arrow_pixmap("down", pal["TEXT"])
    base = _STYLESHEET_TEMPLATE.format(
        FONT_FAMILY=font,
        ARROW_UP=arrow_up, ARROW_DOWN=arrow_down,
        **pal,
    )
    return base + "\n" + extra


_STYLESHEET_TEMPLATE = """
QMainWindow, QWidget {{
    background-color: {BG_DARK};
    color: {TEXT};
    /* Theme-driven font-family — wisselt mee met de geselecteerde theme. */
    font-family: {FONT_FAMILY};
    font-size: 9pt;
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

/* Selectie-overlay is semi-transparant zodat de cue-color-tint die
   QTreeWidgetItem.setBackground neerlegt door de selectie heen blijft
   schijnen. Anders verdwijnt 'n oranje cue volledig zodra je 'm klikt. */
QTreeWidget::item:selected {{
    background: rgba(58, 162, 230, 90);
    color: {TEXT};
}}

QTreeWidget::item:selected:!active {{
    background: rgba(58, 162, 230, 70);
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
    padding: 1px 10px;
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
    font-size: 10pt;
}}
QPushButton#goButton:hover {{ background: #4ca44c; }}

QPushButton#stopButton {{
    background: {ERR};
    color: white;
    font-weight: bold;
    min-height: 32px;
}}
QPushButton#stopButton:hover {{ background: #c04a46; }}

/* Showtime gebruikt z'n eigen icon voor de locked-state (rode lock-
   closed glyph), bg blijft default zodat alleen de glyph "spreekt". */

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {BG_MID};
    border: 1px solid {BORDER};
    padding: 1px 6px;
    color: {TEXT};
    min-height: 14px;
    border-radius: 3px;
    /* Forceer onze eigen selectie-kleur — anders pakt Qt de Windows-
       systeemaccent en wordt geselecteerde tekst (bv. nadat een spinbox-
       pijltje focus geeft + auto-select) in de Windows-themakleur
       getoond, vaak oranje. */
    selection-background-color: {SEL_BG};
    selection-color: {TEXT};
}}

QComboBox::drop-down {{ border: none; }}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}

/* Spinbox up/down knoppen — naast elkaar rechts (down links, up rechts),
   ieder full-height. In Qt-stylesheet-mode tekent Qt géén native pijl-
   glyph meer; de driehoeken komen van _make_arrow_pixmap. */
QSpinBox, QDoubleSpinBox {{
    padding-right: 36px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: right;
    right: 18px;
    width: 18px;
    background: {BG_LIGHT};
    border-left: 1px solid {BORDER};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: right;
    right: 0;
    width: 18px;
    background: {BG_LIGHT};
    border-left: 1px solid {BORDER};
    border-top-right-radius: 3px;
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

/* Radio buttons — Qt's default-indicator is op een donker thema bijna
   onzichtbaar (grijs-op-grijs). Custom indicator: ronde knop, en bij
   selectie een oranje dot via een radial-gradient. */
QRadioButton {{
    spacing: 6px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 8px;
}}
QRadioButton::indicator:unchecked {{
    background: {BG_MID};
    border: 1px solid {BORDER};
}}
QRadioButton::indicator:checked {{
    border: 1px solid {ACCENT_ALT};
    background: qradialgradient(
        cx:0.5, cy:0.5, radius:0.5,
        stop:0 {ACCENT_ALT}, stop:0.45 {ACCENT_ALT},
        stop:0.55 {BG_MID}, stop:1 {BG_MID}
    );
}}
QRadioButton:disabled {{ color: {TEXT_DIM}; }}
QRadioButton::indicator:disabled {{ border: 1px solid {BG_LIGHT}; }}

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
    padding: 4px 0;
}}
QMenu::item {{
    /* Brede padding rechts zodat de sneltoets-aanduiding niet tegen
       het label aankruipt; min-width geeft de menu-popup standaard
       wat lucht zodat 'New Presentation Cue   Ctrl+9' niet botst. */
    padding: 4px 32px 4px 18px;
    min-width: 180px;
}}
QMenu::item:selected {{ background: {SEL_BG}; }}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}

QMenuBar {{
    background: {BG_MID};
    color: {TEXT};
}}
QMenuBar::item:selected {{ background: {SEL_BG}; }}
"""
