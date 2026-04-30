"""Transportbalk: GO-knop, Stop All, playhead-indicator, actieve-cue counter,
grote countdown-timer centraal en de spelende cue-naam rechts."""

from __future__ import annotations

from typing import Callable

from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QFrame,
    QSizePolicy, QGridLayout,
)

from .style import ACCENT, ACCENT_ALT, TEXT_DIM, OK


# Resource-paths voor de lock-icons. ``livefire/resources/icons/`` zit
# in de package zodat 'ie meereist met de installer.
_ICONS_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"
_ICON_LOCK_OPEN = _ICONS_DIR / "lock-open.png"
_ICON_LOCK_CLOSED = _ICONS_DIR / "lock-closed.png"
_ICON_LOCK_CLOSED_RED = _ICONS_DIR / "lock-closed-red.png"
_ICON_LOCK_CLOSED_GREEN = _ICONS_DIR / "lock-closed-green.png"


CountdownSource = Callable[[], "tuple[str, float, bool] | None"]
ElapsedSource = Callable[[], "float | None"]


def _fmt_time(seconds: float) -> str:
    total = int(max(0, seconds))
    if total >= 3600:
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"


class TransportWidget(QWidget):
    go_clicked = pyqtSignal()
    stop_all_clicked = pyqtSignal()
    # True = lock aan (UI bevroren tegen destructieve acties), False = uit.
    showtime_toggled = pyqtSignal(bool)
    # Operator wisselt de inspector-zichtbaarheid via de transport-knop.
    # MainWindow connect 'm aan een slot dat self.inspector.setVisible() doet.
    inspector_toggled = pyqtSignal(bool)

    def __init__(
        self,
        parent=None,
        countdown_source: CountdownSource | None = None,
        elapsed_source: ElapsedSource | None = None,
    ):
        super().__init__(parent)
        # Buitenste VBox met twee secties:
        #   Row 1 (HBox): GO/Stop (dubbel hoog) + Showtime + Inspector-
        #                 toggle + sep + labels + countdown + name
        #   Row 2 (HBox): cue-toolbar over de volle breedte
        # Deze structuur laat de transport groeien zodra de toolbar
        # wrapt — geen Grid-row-height-magie nodig.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum,
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # ---- ROW 1 — transport-balk (alle controls + countdown) --------
        # Wrapper-widget zodat outer.addWidget() z'n hoogte kan claimen
        # (een raw QHBoxLayout heeft geen geometry van zichzelf). Geen
        # maxHeight-cap — REMAIN mag op een breed scherm flink groter
        # dan GO/Stop worden; dat is precies de QLab-stijl.
        row1_widget = QWidget()
        row1 = QHBoxLayout(row1_widget)
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(8)

        # Beide knoppen identieke fixed-width zodat ze visueel gelijk zijn.
        BTN_W = 120
        self.btn_go = QPushButton("GO")
        self.btn_go.setObjectName("goButton")
        self.btn_go.setToolTip("Start the cue at the playhead (Space)")
        self.btn_go.setFixedSize(BTN_W, 80)
        self.btn_go.clicked.connect(self.go_clicked.emit)
        row1.addWidget(self.btn_go)

        self.btn_stop = QPushButton("Stop All")
        self.btn_stop.setObjectName("stopButton")
        self.btn_stop.setToolTip("Stop all active cues immediately (Escape)")
        self.btn_stop.setFixedSize(BTN_W, 80)
        self.btn_stop.clicked.connect(self.stop_all_clicked.emit)
        row1.addWidget(self.btn_stop)

        # Showtime + Inspector-toggle in een kleine vbox naast elkaar (twee
        # knoppen op enkele hoogte stapelen — past in de 80-px row).
        controls_col = QVBoxLayout()
        controls_col.setContentsMargins(0, 0, 0, 0)
        controls_col.setSpacing(4)

        self.btn_showtime = QPushButton(" Showtime")
        self.btn_showtime.setObjectName("showtimeButton")
        self.btn_showtime.setCheckable(True)
        self.btn_showtime.setFixedSize(140, 36)
        showtime_font = QFont()
        showtime_font.setPointSize(10)
        showtime_font.setBold(True)
        self.btn_showtime.setFont(showtime_font)
        self._icon_lock_open = (
            QIcon(str(_ICON_LOCK_OPEN)) if _ICON_LOCK_OPEN.is_file() else QIcon()
        )
        # Locked-state pakt de GROENE variant zodat alleen de glyph kleurt
        # i.p.v. de hele knop-achtergrond. Bg blijft default (donker).
        self._icon_lock_closed = (
            QIcon(str(_ICON_LOCK_CLOSED_GREEN))
            if _ICON_LOCK_CLOSED_GREEN.is_file()
            else QIcon(str(_ICON_LOCK_CLOSED))
            if _ICON_LOCK_CLOSED.is_file()
            else QIcon()
        )
        self.btn_showtime.setIcon(self._icon_lock_open)
        self.btn_showtime.setIconSize(QSize(24, 24))
        self.btn_showtime.setToolTip(
            "Showtime lock: blocks destructive edits (Delete, drag, "
            "inspector changes) so an accidental click can't break a "
            "running show. GO and Stop All stay live."
        )
        self.btn_showtime.toggled.connect(self._on_showtime_toggled)
        controls_col.addWidget(self.btn_showtime)

        self.btn_inspector = QPushButton("Inspector")
        self.btn_inspector.setCheckable(True)
        self.btn_inspector.setChecked(True)  # default zichtbaar
        self.btn_inspector.setFixedSize(140, 36)
        inspector_font = QFont()
        inspector_font.setPointSize(9)
        self.btn_inspector.setFont(inspector_font)
        self.btn_inspector.setToolTip(
            "Show or hide the inspector pane on the right. Useful op kleine "
            "schermen wanneer je de cuelist op breedte nodig hebt."
        )
        self.btn_inspector.toggled.connect(self.inspector_toggled.emit)
        controls_col.addWidget(self.btn_inspector)

        row1.addLayout(controls_col)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        row1.addWidget(sep)

        # NEXT-tegel — kleine caps-label "NEXT" boven, grote cue-naam
        # eronder. Lettertype is Segoe UI Light (display-stijl) voor de
        # naam zelf; caps-label blijft semibold voor leesbaarheid.
        # Font-size wordt dynamisch aangepast in _adjust_responsive_fonts.
        self._info_font_pt = 14  # base; resizeEvent past 'm aan
        self._info_font = QFont("Segoe UI Light")
        self._info_font.setPointSize(self._info_font_pt)

        # ---- LINKER kolom: NEXT (boven) + NOW PLAYING (onder) ---------
        # Verticaal gecentered via addStretch boven+onder zodat 't pakket
        # netjes in 't midden van de row staat i.p.v. top-aligned.
        names_col = QVBoxLayout()
        names_col.setContentsMargins(0, 0, 0, 0)
        names_col.setSpacing(2)
        names_col.addStretch(1)

        self.lbl_playhead = QLabel()
        self.lbl_playhead.setFont(self._info_font)
        self.lbl_playhead.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_playhead.setToolTip("The cue that will fire on the next GO")
        self.lbl_playhead.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        names_col.addWidget(self.lbl_playhead)
        # Initiële render zodat 't label niet leeg start.
        self.set_playhead(0, 0, "")
        # ACTIVE-label blijft achter als hidden widget — set_active_count
        # is een no-op nu, maar de Public API blijft compatible.
        self.lbl_active = QLabel()
        self.lbl_active.hide()

        self.lbl_countdown_name = QLabel()
        self.lbl_countdown_name.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_countdown_name.setFont(self._info_font)
        self.lbl_countdown_name.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_countdown_name.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        names_col.addWidget(self.lbl_countdown_name)
        names_col.addStretch(1)
        # Stretch=0 → claim alleen de natuurlijke breedte. De timer-kolom
        # erna pakt dan alle resterende ruimte voor 't dominant-centrum.
        row1.addLayout(names_col, 0)

        sep_next_now = QFrame()
        sep_next_now.setFrameShape(QFrame.Shape.VLine)
        sep_next_now.setFrameShadow(QFrame.Shadow.Sunken)
        row1.addWidget(sep_next_now)

        # ---- CENTER — klassieke QLab-stijl: grote REMAIN, kleine ELAPSED
        # Eén enorme countdown vult 't midden. Onder de countdown 'n klein
        # 'elapsed 0:34'-label — minder prominent, geeft alleen contextuele
        # informatie. Beide centrum-uitgelijnd, monospace zodat de digits
        # niet schokken bij elke tick.
        self._timer_font_pt = 56  # base; resizeEvent past 'm aan
        self._timer_font = QFont("Consolas")
        self._timer_font.setPointSize(self._timer_font_pt)
        self._timer_font.setBold(True)

        self._elapsed_font_pt = 11  # base voor 't kleine elapsed-label
        self._elapsed_font = QFont("Consolas")
        self._elapsed_font.setPointSize(self._elapsed_font_pt)

        center_col = QVBoxLayout()
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(0)
        # Verticaal centreren — dezelfde truc als bij names_col.
        center_col.addStretch(1)

        # Big REMAIN — was lbl_countdown; alias blijft voor bestaande code.
        self.lbl_countdown = QLabel("—:—")
        self.lbl_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_countdown.setFont(self._timer_font)
        self.lbl_countdown.setStyleSheet(f"color: {ACCENT};")
        self.lbl_countdown.setToolTip(
            "Remaining time of the longest-running audio cue. With infinite "
            "loop it counts up (prefix +)."
        )
        # Forse min-width zodat de countdown ook bij smal venster nog
        # leesbaar is. 280 px past comfortabel "00:00" op 56 pt.
        self.lbl_countdown.setMinimumWidth(280)
        center_col.addWidget(self.lbl_countdown)

        # Tiny ELAPSED-label, dimkleur — onder de countdown.
        self.lbl_elapsed = QLabel("elapsed —:—")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_elapsed.setFont(self._elapsed_font)
        self.lbl_elapsed.setStyleSheet(f"color: {TEXT_DIM};")
        self.lbl_elapsed.setToolTip("Elapsed time of the playing cue")
        center_col.addWidget(self.lbl_elapsed)
        center_col.addStretch(1)

        # Stretch=1 zodat de timer-kolom alle resterende horizontale
        # ruimte claimt — de QLabel zelf is center-aligned, dus de
        # countdown-text staat in 't midden van die brede strook.
        row1.addLayout(center_col, 1)

        outer.addWidget(row1_widget)

        # ---- ROW 2 — cue-toolbar over volle breedte --------------------
        # MainWindow injecteert de eigenlijke widget via set_cue_toolbar();
        # de FlowLayout binnenin wrapt naar 'n volgende regel als 't te
        # smal wordt. De holder zelf heeft sizePolicy MinimumExpanding op
        # vertical zodat 'ie meegroei't met die wrap.
        self._cue_toolbar_holder = QWidget()
        self._cue_toolbar_holder.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum,
        )
        self._cue_toolbar_lay = QHBoxLayout(self._cue_toolbar_holder)
        self._cue_toolbar_lay.setContentsMargins(0, 0, 0, 0)
        self._cue_toolbar_lay.setSpacing(2)
        outer.addWidget(self._cue_toolbar_holder)

        # ---- Refresh-timer voor countdown ----------------------------------
        self._countdown_source = countdown_source
        self._elapsed_source = elapsed_source
        self._cd_timer = QTimer(self)
        self._cd_timer.setInterval(100)  # 10 Hz is ruim genoeg
        self._cd_timer.timeout.connect(self._refresh_countdown)
        if countdown_source is not None:
            self._cd_timer.start()

    # ---- public API --------------------------------------------------------

    @staticmethod
    def _html_escape(text: str) -> str:
        return (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

    def set_playhead(self, index: int, total: int, cue_label: str = "") -> None:
        """NEXT-tile: kleine "NEXT"-caps in oranje, daaronder de cue-naam
        of "—" als 'r geen volgende is. Twee regels in één label."""
        if total == 0:
            value = "—"
        elif index >= total:
            value = f"end ({total})"
        else:
            value = f"{index + 1}/{total}"
            if cue_label:
                value += f" · {cue_label}"
        self.lbl_playhead.setText(
            f'<span style="color:{ACCENT_ALT};font-size:8pt;'
            f'letter-spacing:1px;">NEXT</span><br>'
            f'<span style="color:white;">{self._html_escape(value)}</span>'
        )

    def set_active_count(self, n: int) -> None:
        """No-op: ACTIVE-tile is niet meer in de header. Method blijft
        bestaan zodat bestaande callers (mainwindow) niet breken."""
        return

    def resizeEvent(self, event):  # noqa: N802 — Qt convention
        super().resizeEvent(event)
        self._adjust_responsive_fonts()

    def _adjust_responsive_fonts(self) -> None:
        """Pas de font-sizes van de header-tiles aan op de huidige
        widget-BREEDTE. Brede vensters krijgen grote display-fonts;
        smalle vensters laten alles gracieus krimpen tot 't nog net
        leesbaar blijft.

        Schaal-bereiken (lineair in venster-breedte):
        - 800 px breed → timers 24 pt, info 11 pt
        - 1800 px breed → timers 64 pt, info 22 pt
        Tussenwaarden interpoleren.
        """
        w = max(400, self.width())
        # Lineaire interpolatie tussen (800, 24) en (1800, 64) voor timers
        # en (800, 11) en (1800, 22) voor info-labels.
        def _scale(value_min: int, value_max: int,
                   width_min: int = 800, width_max: int = 1800) -> int:
            t = (w - width_min) / max(1, width_max - width_min)
            t = max(0.0, min(1.0, t))
            return int(round(value_min + t * (value_max - value_min)))

        # Klassieke QLab-stijl: REMAIN = grote countdown midden in de row.
        # Schaalt mee met breedte 36..72 pt. Elapsed blijft een klein
        # caption-label van 10..14 pt.
        timer_pt = _scale(36, 72)
        if timer_pt != self._timer_font_pt:
            self._timer_font_pt = timer_pt
            self._timer_font.setPointSize(timer_pt)
            self.lbl_countdown.setFont(self._timer_font)
        elapsed_pt = _scale(10, 14)
        if elapsed_pt != self._elapsed_font_pt:
            self._elapsed_font_pt = elapsed_pt
            self._elapsed_font.setPointSize(elapsed_pt)
            self.lbl_elapsed.setFont(self._elapsed_font)
        info_pt = _scale(11, 18)
        if info_pt != self._info_font_pt:
            self._info_font_pt = info_pt
            self._info_font.setPointSize(info_pt)
            self.lbl_playhead.setFont(self._info_font)
            self.lbl_countdown_name.setFont(self._info_font)
            # Re-render om 't HTML-fragment opnieuw met nieuwe font-sizes
            # te tekenen (caps-label heeft eigen font-size in de HTML).
            self._refresh_countdown()

    def set_cue_toolbar(self, widget: QWidget) -> None:
        """MainWindow propt zijn cue-toolbar in de slot onder Showtime.
        Idempotent: vorig kind wordt netjes losgekoppeld."""
        while self._cue_toolbar_lay.count():
            item = self._cue_toolbar_lay.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
        self._cue_toolbar_lay.addWidget(widget, 1)

    # ---- showtime-lock -----------------------------------------------------

    def is_showtime(self) -> bool:
        return self.btn_showtime.isChecked()

    def set_showtime(self, on: bool) -> None:
        """Programmatic toggle. Vermijdt een feedback-loop omdat
        QPushButton.setChecked geen ``toggled``-signal stuurt als de
        state al klopt."""
        if self.btn_showtime.isChecked() != on:
            self.btn_showtime.setChecked(on)

    def _on_showtime_toggled(self, on: bool) -> None:
        # Visuele feedback: gesloten slot-icoon als de lock aan staat,
        # open slot wanneer 't uit is. De Qt :checked-pseudoclass kleurt
        # de bg al lichter, dus de combinatie laat zonder twijfel zien
        # of de lock actief is.
        self.btn_showtime.setIcon(
            self._icon_lock_closed if on else self._icon_lock_open
        )
        self.showtime_toggled.emit(on)

    _FLASH_STYLE = (
        "QPushButton#showtimeButton {"
        "  background: #c0392b;"
        "  color: white;"
        "  border: 2px solid #ff6b5b;"
        "  border-radius: 6px;"
        "}"
    )

    def flash_blocked(self) -> None:
        """Twee-keer-knipper-flash op de showtime-knop wanneer een edit
        geblockd is. Cycle: rood (200 ms) → off (180 ms) → rood (200 ms)
        → off. Een tweede call midden in 'n flash-cycle herstart van 0
        zonder de UI te brokken (singleShots blijven gestapeld lopen
        maar zetten de stijl idempotent)."""
        on_style = self._FLASH_STYLE
        btn = self.btn_showtime
        # Twee korte pulsen — leesbaarder als 'attention-grabber' dan een
        # statische rode kleur, vooral als de knop al rood is door :checked.
        QTimer.singleShot(0, lambda: btn.setStyleSheet(on_style))
        QTimer.singleShot(200, lambda: btn.setStyleSheet(""))
        QTimer.singleShot(380, lambda: btn.setStyleSheet(on_style))
        QTimer.singleShot(580, lambda: btn.setStyleSheet(""))

    # ---- countdown ---------------------------------------------------------

    def _refresh_countdown(self) -> None:
        info = self._countdown_source() if self._countdown_source else None
        elapsed = self._elapsed_source() if self._elapsed_source else None
        if info is None:
            self.lbl_countdown.setText("—:—")
            self.lbl_elapsed.setText("elapsed —:—")
            self.lbl_countdown_name.setText(
                f'<span style="color:{TEXT_DIM};font-size:8pt;'
                f'letter-spacing:1px;">NOW PLAYING</span><br>'
                f'<span style="color:{TEXT_DIM};font-style:italic;">—</span>'
            )
            return
        name, seconds, is_countdown = info
        prefix = "" if is_countdown else "+"
        self.lbl_countdown.setText(f"{prefix}{_fmt_time(seconds)}")
        # Klein elapsed-label met "elapsed"-prefix in dimkleur — geeft
        # context zonder de prominente REMAIN te beconcurreren.
        self.lbl_elapsed.setText(
            f"elapsed {_fmt_time(elapsed)}" if elapsed is not None
            else "elapsed —:—"
        )
        self.lbl_countdown_name.setText(
            f'<span style="color:{ACCENT};font-size:8pt;'
            f'letter-spacing:1px;">NOW PLAYING</span><br>'
            f'<span style="color:white;">{self._html_escape(name)}</span>'
        )
