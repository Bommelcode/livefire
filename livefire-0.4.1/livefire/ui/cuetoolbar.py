"""QLab-stijl toolbar boven de cuelist: knoppen voor nieuwe cues van elk
type + delete / renumber / move. Emit signals; de MainWindow koppelt ze
aan de bestaande actions."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QFrame, QToolButton,
)

from ..cues import CueType
from ..i18n import t


# QLab gebruikt per cue-type een eigen kleur-accent. We doen hetzelfde zodat
# de knoppen meteen herkenbaar zijn.
_CUE_TYPE_ACCENTS = {
    CueType.AUDIO:        "#2980b9",  # blauw
    CueType.VIDEO:        "#16a085",  # teal
    CueType.IMAGE:        "#0e7490",  # cyaan-teal (image = "stille video")
    CueType.PRESENTATION: "#b03a2e",  # PowerPoint-rood
    CueType.NETWORK:      "#5b6abf",  # indigo (OSC = network/control)
    CueType.FADE:         "#c9a227",  # geel
    CueType.WAIT:         "#606060",  # grijs
    CueType.STOP:         "#c0392b",  # rood
    CueType.START:        "#2e8b57",  # groen
    CueType.GROUP:        "#7d3c98",  # paars
    CueType.MEMO:         "#d35400",  # oranje
}

_CUE_TYPE_ORDER = [
    CueType.AUDIO, CueType.VIDEO, CueType.IMAGE, CueType.PRESENTATION,
    CueType.NETWORK,
    CueType.FADE, CueType.WAIT, CueType.STOP,
    CueType.START, CueType.GROUP, CueType.MEMO,
]

_CUE_TYPE_TIPS = {
    CueType.AUDIO:        "Nieuwe Audio-cue (Ctrl+1)",
    CueType.VIDEO:        "Nieuwe Video-cue (Ctrl+8)",
    CueType.IMAGE:        "Nieuwe Afbeelding-cue (Ctrl+0)",
    CueType.PRESENTATION: "Nieuwe Presentatie-cue (Ctrl+9)",
    CueType.NETWORK:      "Nieuwe Network-cue (OSC-out)",
    CueType.FADE:         "Nieuwe Fade-cue (Ctrl+2)",
    CueType.WAIT:         "Nieuwe Wait-cue (Ctrl+3)",
    CueType.STOP:         "Nieuwe Stop-cue (Ctrl+4)",
    CueType.GROUP:        "Nieuwe Group-cue (Ctrl+5)",
    CueType.MEMO:         "Nieuwe Memo-cue (Ctrl+6)",
    CueType.START:        "Nieuwe Start-cue (Ctrl+7)",
}


def _swatch_icon(hex_color: str, size: int = 10) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(hex_color))
    return QIcon(pm)


class CueToolbar(QWidget):
    """Toolbar die QLab's cue-toolbar nabootst: nieuwe-cue knoppen + delete /
    renumber / move up / move down."""

    new_cue = pyqtSignal(str)       # cue_type
    delete_selected = pyqtSignal()
    renumber = pyqtSignal()
    move_up = pyqtSignal()
    move_down = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)

        for ct in _CUE_TYPE_ORDER:
            btn = QPushButton(t(f"cuetype.{ct}"))
            btn.setIcon(_swatch_icon(_CUE_TYPE_ACCENTS[ct]))
            btn.setIconSize(QSize(10, 10))
            btn.setToolTip(_CUE_TYPE_TIPS[ct])
            btn.setFlat(False)
            btn.setMinimumHeight(26)
            # Capture ct via default-arg om late-binding in de lambda te
            # voorkomen. Niet 't' noemen — dat shadowt de i18n-import.
            btn.clicked.connect(lambda _checked, ctype=ct: self.new_cue.emit(ctype))
            lay.addWidget(btn)

        lay.addWidget(self._separator())

        btn_del = QPushButton("Verwijderen")
        btn_del.setToolTip("Verwijder de geselecteerde cue(s) (Delete)")
        btn_del.setMinimumHeight(26)
        btn_del.clicked.connect(self.delete_selected.emit)
        lay.addWidget(btn_del)

        btn_ren = QPushButton("Hernummeren")
        btn_ren.setToolTip("Hernummer alle cues oplopend vanaf 1")
        btn_ren.setMinimumHeight(26)
        btn_ren.clicked.connect(self.renumber.emit)
        lay.addWidget(btn_ren)

        lay.addWidget(self._separator())

        btn_up = QPushButton("↑")
        btn_up.setToolTip("Verplaats geselecteerde cue(s) omhoog (Ctrl+↑)")
        btn_up.setFixedWidth(32)
        btn_up.setMinimumHeight(26)
        btn_up.clicked.connect(self.move_up.emit)
        lay.addWidget(btn_up)

        btn_down = QPushButton("↓")
        btn_down.setToolTip("Verplaats geselecteerde cue(s) omlaag (Ctrl+↓)")
        btn_down.setFixedWidth(32)
        btn_down.setMinimumHeight(26)
        btn_down.clicked.connect(self.move_down.emit)
        lay.addWidget(btn_down)

        lay.addStretch(1)

    @staticmethod
    def _separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep
