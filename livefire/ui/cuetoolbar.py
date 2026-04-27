"""QLab-stijl toolbar boven de cuelist: knoppen voor nieuwe cues van elk
type + delete / renumber / move. Emit signals; de MainWindow koppelt ze
aan de bestaande actions.

De cue-type-knoppen gebruiken witte glyph-iconen op de donkere knop-
achtergrond (geen tekstlabels). Iedere glyph is een vector die we via
QPainter zelf tekenen — geen asset-bestanden nodig. Hover toont de
volledige naam + sneltoets via tooltip."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt, QPointF, QRectF, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QFrame,
)

from ..cues import CueType
from ..i18n import t


_CUE_TYPE_ORDER = [
    CueType.AUDIO, CueType.VIDEO, CueType.IMAGE, CueType.PRESENTATION,
    CueType.NETWORK, CueType.DMX,
    CueType.FADE, CueType.WAIT, CueType.STOP,
    CueType.START, CueType.GROUP, CueType.MEMO,
]

_CUE_TYPE_TIPS = {
    CueType.AUDIO:        "New Audio cue (Ctrl+1)",
    CueType.VIDEO:        "New Video cue (Ctrl+2)",
    CueType.IMAGE:        "New Image cue (Ctrl+3)",
    CueType.PRESENTATION: "New Presentation cue (Ctrl+4)",
    CueType.NETWORK:      "New Network cue (Ctrl+5)",
    CueType.DMX:          "New DMX cue (Ctrl+Shift+D)",
    CueType.FADE:         "New Fade cue (Ctrl+6)",
    CueType.WAIT:         "New Wait cue (Ctrl+7)",
    CueType.STOP:         "New Stop cue (Ctrl+8)",
    CueType.GROUP:        "New Group cue (Ctrl+9)",
    CueType.MEMO:         "New Memo cue (Ctrl+0)",
    CueType.START:        "New Start cue",
}


# ---- glyph drawers ---------------------------------------------------------
#
# Iedere drawer tekent in een 18×18 box rond het midden, witte vorm op
# transparante achtergrond. Geometrie is uitgedrukt in pixels — niet
# schaalbaar, omdat de toolbar-iconen op één maat staan. Voor andere
# maten zou je de QPainter scaleren via QTransform.

# Stroke-helpers — switch tussen pure fill (geen outline-bulge) en pure
# stroke (vaste 1.0 line-width in source-coords). Filled shapes krijgen
# NoPen zodat hun rand niet naar buiten dijt; stroke-only shapes krijgen
# NoBrush zodat de binnenkant transparant blijft.
_WHITE = QColor("white")
# Niet-cosmetisch: de pen schaalt mee met painter.scale() in _glyph_icon.
# Bij supersampling (4×) wordt 1.0 source-coords dus 4 fysieke pixels in
# de pixmap; na de downsample naar de toolbar-iconSize is 't ~1 display-px.
_PEN = QPen(_WHITE, 0.8)


def _stroke(p: QPainter) -> None:
    p.setPen(_PEN)
    p.setBrush(Qt.GlobalColor.transparent)


def _fill(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_WHITE)


def _draw_audio(p: QPainter) -> None:
    # Speaker (rechthoek + cone) + één geluidsboog.
    _fill(p)
    p.drawRect(3, 7, 3, 4)
    cone = QPolygonF([QPointF(6, 7), QPointF(10, 4),
                      QPointF(10, 14), QPointF(6, 11)])
    p.drawPolygon(cone)
    _stroke(p)
    p.drawArc(QRectF(11, 5, 4, 8), 270 * 16, 180 * 16)


def _draw_video(p: QPainter) -> None:
    # Filmstrip-rechthoek met play-driehoek erin.
    _stroke(p)
    p.drawRoundedRect(QRectF(2.5, 4.5, 13, 9), 1, 1)
    _fill(p)
    play = QPolygonF([QPointF(7, 6), QPointF(11, 9), QPointF(7, 12)])
    p.drawPolygon(play)


def _draw_image(p: QPainter) -> None:
    # Frame met zon + bergtop.
    _stroke(p)
    p.drawRoundedRect(QRectF(2.5, 3.5, 13, 11), 1, 1)
    _fill(p)
    p.drawEllipse(QRectF(11, 5, 3, 3))
    mountain = QPolygonF([QPointF(3, 13), QPointF(8, 7), QPointF(13, 13)])
    p.drawPolygon(mountain)


def _draw_presentation(p: QPainter) -> None:
    # Scherm op een statief.
    _fill(p)
    p.drawRect(2, 3, 14, 8)
    p.drawRect(8, 11, 2, 3)
    p.drawRect(5, 14, 8, 1)


def _draw_network(p: QPainter) -> None:
    # Drie verbonden knooppunten (driehoek-graaf).
    _stroke(p)
    p.drawLine(9, 3, 3, 13)
    p.drawLine(9, 3, 15, 13)
    p.drawLine(3, 13, 15, 13)
    _fill(p)
    for x, y in [(9, 3), (3, 13), (15, 13)]:
        p.drawEllipse(QRectF(x - 2, y - 2, 4, 4))


def _draw_dmx(p: QPainter) -> None:
    # Vijf "fader"-balken met variërende heights — net zoals een DMX-
    # console-strip. Onder een dunne basislijn als grondvlak.
    _fill(p)
    bars = [
        (3, 5, 2, 9),    # x, y, w, h (h tot bottom 14)
        (6, 8, 2, 6),
        (9, 4, 2, 10),
        (12, 7, 2, 7),
        (15, 6, 2, 8),
    ]
    # Bar widths > 18 bbox — laatste loopt iets buiten; pas aan
    bars = [
        (3, 5, 2, 9),
        (6, 8, 2, 6),
        (9, 4, 2, 10),
        (12, 7, 2, 7),
        (14, 6, 2, 8),
    ]
    for x, y, w, h in bars:
        p.drawRect(x, y, w, h)
    _stroke(p)
    p.drawLine(2, 14, 16, 14)


def _draw_fade(p: QPainter) -> None:
    # Wedge-driehoek = volume die afloopt.
    _fill(p)
    wedge = QPolygonF([QPointF(2, 14), QPointF(16, 14), QPointF(16, 4)])
    p.drawPolygon(wedge)


def _draw_wait(p: QPainter) -> None:
    # Zandloper.
    _fill(p)
    top = QPolygonF([QPointF(4, 3), QPointF(14, 3), QPointF(9, 9)])
    bottom = QPolygonF([QPointF(9, 9), QPointF(14, 15), QPointF(4, 15)])
    p.drawPolygon(top)
    p.drawPolygon(bottom)


def _draw_stop(p: QPainter) -> None:
    _fill(p)
    p.drawRect(4, 4, 10, 10)


def _draw_start(p: QPainter) -> None:
    # Play-driehoek (rechtswijzend).
    _fill(p)
    play = QPolygonF([QPointF(5, 3), QPointF(15, 9), QPointF(5, 15)])
    p.drawPolygon(play)


def _draw_group(p: QPainter) -> None:
    # Drie gestapelde regels (lijst-icoon).
    _fill(p)
    p.drawRect(3, 4, 12, 2)
    p.drawRect(3, 8, 12, 2)
    p.drawRect(3, 12, 12, 2)


def _draw_memo(p: QPainter) -> None:
    # Notitieblad met regels.
    _stroke(p)
    p.drawRoundedRect(QRectF(3.5, 2.5, 10, 13), 1, 1)
    _fill(p)
    p.drawRect(5, 5, 7, 1)
    p.drawRect(5, 8, 7, 1)
    p.drawRect(5, 11, 5, 1)


_GLYPH_DRAWERS = {
    CueType.AUDIO:        _draw_audio,
    CueType.VIDEO:        _draw_video,
    CueType.IMAGE:        _draw_image,
    CueType.PRESENTATION: _draw_presentation,
    CueType.NETWORK:      _draw_network,
    CueType.DMX:          _draw_dmx,
    CueType.FADE:         _draw_fade,
    CueType.WAIT:         _draw_wait,
    CueType.STOP:         _draw_stop,
    CueType.START:        _draw_start,
    CueType.GROUP:        _draw_group,
    CueType.MEMO:         _draw_memo,
}


def _glyph_icon(cue_type: str, size: int = 18) -> QIcon:
    """Witte glyph-icoon voor een cue-type, transparante achtergrond.

    Supersample-aanpak voor scherpte: render op 4× source-resolutie
    (72×72 fysiek voor een 18-coord drawer) en laat Qt naar de
    toolbar-iconSize downsamplen. Dat is veel scherper dan native op
    18×18 of 20×20 tekenen — Qt's smooth-downsample bewaart fijne
    randen die je anders kwijtraakt aan pixel-rounding.
    """
    supersample = 4
    phys = size * supersample
    pm = QPixmap(phys, phys)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.scale(supersample, supersample)  # drawers werken in 18-coord systeem
    drawer = _GLYPH_DRAWERS.get(cue_type)
    if drawer is not None:
        drawer(p)
    p.end()
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
            btn = QPushButton()
            btn.setIcon(_glyph_icon(ct))
            btn.setIconSize(QSize(20, 20))
            # Tooltip combineert sneltoets én cue-type-naam — die zaten
            # eerst in label + tip; nu beide in tip omdat de label weg is.
            btn.setToolTip(f"{t(f'cuetype.{ct}')} — {_CUE_TYPE_TIPS[ct]}")
            btn.setFlat(False)
            btn.setFixedSize(34, 30)
            # Capture ct via default-arg om late-binding in de lambda te
            # voorkomen. Niet 't' noemen — dat shadowt de i18n-import.
            btn.clicked.connect(lambda _checked, ctype=ct: self.new_cue.emit(ctype))
            lay.addWidget(btn)

        lay.addWidget(self._separator())

        btn_del = QPushButton("Delete")
        btn_del.setToolTip("Delete the selected cue(s) (Delete)")
        btn_del.setMinimumHeight(26)
        btn_del.clicked.connect(self.delete_selected.emit)
        lay.addWidget(btn_del)

        btn_ren = QPushButton("Renumber")
        btn_ren.setToolTip("Renumber all cues sequentially starting from 1")
        btn_ren.setMinimumHeight(26)
        btn_ren.clicked.connect(self.renumber.emit)
        lay.addWidget(btn_ren)

        lay.addWidget(self._separator())

        btn_up = QPushButton("↑")
        btn_up.setToolTip("Move selected cue(s) up (Ctrl+↑)")
        btn_up.setFixedWidth(32)
        btn_up.setMinimumHeight(26)
        btn_up.clicked.connect(self.move_up.emit)
        lay.addWidget(btn_up)

        btn_down = QPushButton("↓")
        btn_down.setToolTip("Move selected cue(s) down (Ctrl+↓)")
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
