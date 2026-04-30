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
        row1 = QHBoxLayout()
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
        # Locked-state pakt de RODE variant zodat alleen de glyph rood kleurt
        # i.p.v. de hele knop-achtergrond. Bg blijft default (donker).
        self._icon_lock_closed = (
            QIcon(str(_ICON_LOCK_CLOSED_RED))
            if _ICON_LOCK_CLOSED_RED.is_file()
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

        # Twee status-tegels (NEXT, ACTIVE) in dezelfde stijl: kleine
        # caps-label bovenaan, grote waarde eronder. Elk heeft 'n eigen
        # accent-kleur zodat de drie onderdelen visueel los blijven.
        # Helper-methodes onderaan formatteren de HTML-string.
        info_font = QFont("Segoe UI Semibold")
        info_font.setPointSize(13)

        self.lbl_playhead = QLabel()
        self.lbl_playhead.setFont(info_font)
        self.lbl_playhead.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_playhead.setToolTip("The cue that will fire on the next GO")
        self.lbl_playhead.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        row1.addWidget(self.lbl_playhead, 1)

        sep_inner = QFrame()
        sep_inner.setFrameShape(QFrame.Shape.VLine)
        sep_inner.setFrameShadow(QFrame.Shadow.Sunken)
        row1.addWidget(sep_inner)

        self.lbl_active = QLabel()
        self.lbl_active.setFont(info_font)
        self.lbl_active.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_active.setToolTip("Number of cues currently playing")
        self.lbl_active.setMinimumWidth(0)
        row1.addWidget(self.lbl_active)

        sep_inner2 = QFrame()
        sep_inner2.setFrameShape(QFrame.Shape.VLine)
        sep_inner2.setFrameShadow(QFrame.Shadow.Sunken)
        row1.addWidget(sep_inner2)
        # Initiële render zodat de labels niet leeg starten.
        self.set_playhead(0, 0, "")
        self.set_active_count(0)

        # NOW PLAYING tile — naam van de spelende cue (zelfde stijl als
        # NEXT/ACTIVE). Stretcht naar links.
        self.lbl_countdown_name = QLabel()
        self.lbl_countdown_name.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_countdown_name.setFont(info_font)
        self.lbl_countdown_name.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_countdown_name.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        row1.addWidget(self.lbl_countdown_name, 1)

        # Twee grote timers achter de naam — ELAPSED + REMAIN, beide in
        # monospace zodat de digits niet schokken bij elke tick.
        timer_font = QFont("Consolas")
        timer_font.setPointSize(36)
        timer_font.setBold(True)

        # Beide timers krijgen 'n vaste min-width zodat ze altijd zichtbaar
        # zijn (anders verdwijnen ze naar 0 px omdat de NOW-PLAYING tile
        # met stretch=1 alle ruimte opslokt). 140 px past 'm:ss\nXX:XX
        # bij 36pt monospace. Verticale policy: Preferred zodat 'ie netjes
        # uitgelijnd staat op de label-baseline.
        TIMER_MIN_W = 140
        self.lbl_elapsed = QLabel("—:—")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_elapsed.setFont(timer_font)
        self.lbl_elapsed.setStyleSheet(f"color: {OK};")
        self.lbl_elapsed.setToolTip("Elapsed time of the playing cue")
        self.lbl_elapsed.setMinimumWidth(TIMER_MIN_W)
        row1.addWidget(self.lbl_elapsed)

        # Backwards-compat alias zodat bestaande code (autosave etc.) die
        # 'lbl_countdown' aanroept blijft werken — 't is nu de REMAIN-tile.
        self.lbl_countdown = QLabel("—:—")
        self.lbl_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_countdown.setFont(timer_font)
        self.lbl_countdown.setStyleSheet(f"color: {ACCENT};")
        self.lbl_countdown.setToolTip(
            "Remaining time of the longest-running audio cue. With infinite "
            "loop it counts up (prefix +)."
        )
        self.lbl_countdown.setMinimumWidth(TIMER_MIN_W)
        row1.addWidget(self.lbl_countdown)

        outer.addLayout(row1)

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
        """ACTIVE-tile: groen "ACTIVE" boven, count eronder. Count wordt
        groen opgelicht zodra ≥1 cue speelt zodat 'ie zichtbaar is op
        afstand."""
        value_color = OK if n > 0 else TEXT_DIM
        self.lbl_active.setText(
            f'<span style="color:{OK};font-size:8pt;'
            f'letter-spacing:1px;">ACTIVE</span><br>'
            f'<span style="color:{value_color};">{n}</span>'
        )

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
            self.lbl_elapsed.setText("—:—")
            self.lbl_countdown_name.setText(
                f'<span style="color:{TEXT_DIM};font-size:8pt;'
                f'letter-spacing:1px;">NOW PLAYING</span><br>'
                f'<span style="color:{TEXT_DIM};font-style:italic;">—</span>'
            )
            return
        name, seconds, is_countdown = info
        prefix = "" if is_countdown else "+"
        self.lbl_countdown.setText(f"{prefix}{_fmt_time(seconds)}")
        self.lbl_elapsed.setText(
            _fmt_time(elapsed) if elapsed is not None else "—:—"
        )
        self.lbl_countdown_name.setText(
            f'<span style="color:{ACCENT};font-size:8pt;'
            f'letter-spacing:1px;">NOW PLAYING</span><br>'
            f'<span style="color:white;">{self._html_escape(name)}</span>'
        )
