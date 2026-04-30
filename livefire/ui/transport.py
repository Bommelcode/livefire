"""Transportbalk: GO-knop, Stop All, playhead-indicator, actieve-cue counter,
grote countdown-timer centraal en de spelende cue-naam rechts."""

from __future__ import annotations

from typing import Callable

from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QFrame, QGridLayout,
)

from .style import ACCENT, TEXT_DIM


# Resource-paths voor de lock-icons. ``livefire/resources/icons/`` zit
# in de package zodat 'ie meereist met de installer.
_ICONS_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"
_ICON_LOCK_OPEN = _ICONS_DIR / "lock-open.png"
_ICON_LOCK_CLOSED = _ICONS_DIR / "lock-closed.png"


CountdownSource = Callable[[], "tuple[str, float, bool] | None"]


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

    def __init__(self, parent=None, countdown_source: CountdownSource | None = None):
        super().__init__(parent)
        # GridLayout met twee rijen — GO/Stop zijn dubbele hoogte
        # (rowSpan=2), Showtime + cue-toolbar delen de rechter-bovenkolom
        # in twee horizontale strips. Cue-toolbar wordt door MainWindow
        # ingevoegd via set_cue_toolbar(); deze widget reserveert alleen
        # de ruimte ervoor.
        lay = QGridLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(4)

        # Col 0 — GO (dubbel hoog: span 2 rijen)
        self.btn_go = QPushButton("GO")
        self.btn_go.setObjectName("goButton")
        self.btn_go.setToolTip("Start the cue at the playhead (Space)")
        self.btn_go.setMinimumHeight(72)
        self.btn_go.clicked.connect(self.go_clicked.emit)
        lay.addWidget(self.btn_go, 0, 0, 2, 1)

        # Col 1 — Stop All (dubbel hoog: span 2 rijen)
        self.btn_stop = QPushButton("Stop All")
        self.btn_stop.setObjectName("stopButton")
        self.btn_stop.setToolTip("Stop all active cues immediately (Escape)")
        self.btn_stop.setMinimumHeight(72)
        self.btn_stop.clicked.connect(self.stop_all_clicked.emit)
        lay.addWidget(self.btn_stop, 0, 1, 2, 1)

        # ---- Showtime-lock toggle (col 2 row 0) -------------------------
        # Bevriest destructieve UI-acties (Delete, drag-reorder, inspector-
        # edits) zodra het publiek binnen is. GO en Stop All blijven altijd
        # werken — dit is geen freeze van de show, alleen van de editor.
        self.btn_showtime = QPushButton(" Showtime")
        self.btn_showtime.setObjectName("showtimeButton")
        self.btn_showtime.setCheckable(True)
        self.btn_showtime.setMinimumSize(90, 32)
        showtime_font = QFont()
        showtime_font.setPointSize(10)
        showtime_font.setBold(True)
        self.btn_showtime.setFont(showtime_font)
        # Cache de twee icon-states zodat we ze niet elke toggle opnieuw
        # van disk hoeven te lezen. Pad valt terug op leeg-QIcon als 't
        # bestand er niet is — dan toont Qt enkel de tekst, geen crash.
        self._icon_lock_open = (
            QIcon(str(_ICON_LOCK_OPEN)) if _ICON_LOCK_OPEN.is_file() else QIcon()
        )
        self._icon_lock_closed = (
            QIcon(str(_ICON_LOCK_CLOSED)) if _ICON_LOCK_CLOSED.is_file() else QIcon()
        )
        self.btn_showtime.setIcon(self._icon_lock_open)
        self.btn_showtime.setIconSize(QSize(18, 18))
        self.btn_showtime.setToolTip(
            "Showtime lock: blocks destructive edits (Delete, drag, "
            "inspector changes) so an accidental click can't break a "
            "running show. GO and Stop All stay live."
        )
        self.btn_showtime.toggled.connect(self._on_showtime_toggled)
        lay.addWidget(self.btn_showtime, 0, 2)

        # Cue-toolbar slot — row 1, vanaf col 2 doorlopend tot een eind-
        # kolom zodat de toolbar zoveel ruimte krijgt als nodig. Default
        # leeg; MainWindow injecteert via set_cue_toolbar().
        self._cue_toolbar_holder = QWidget()
        self._cue_toolbar_lay = QHBoxLayout(self._cue_toolbar_holder)
        self._cue_toolbar_lay.setContentsMargins(0, 0, 0, 0)
        self._cue_toolbar_lay.setSpacing(2)
        # ColSpan=99 — Qt clipt 'm aan 't aantal echte kolommen, en zo
        # hoeven we niet te tellen wat we hierna toevoegen.
        lay.addWidget(self._cue_toolbar_holder, 1, 2, 1, 99)

        # Col 3 row 0 — separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(sep, 0, 3)

        # Col 4 row 0 — playhead + active in een kleine VBox naast elkaar
        labels_holder = QWidget()
        labels_lay = QHBoxLayout(labels_holder)
        labels_lay.setContentsMargins(0, 0, 0, 0)
        labels_lay.setSpacing(12)
        self.lbl_playhead = QLabel("Playhead: —")
        self.lbl_playhead.setToolTip("The cue that will fire on the next GO")
        labels_lay.addWidget(self.lbl_playhead)
        self.lbl_active = QLabel("Active: 0")
        self.lbl_active.setToolTip("Number of cues currently playing")
        labels_lay.addWidget(self.lbl_active)
        lay.addWidget(labels_holder, 0, 4)

        # Col 5 — stretch
        lay.setColumnStretch(5, 1)

        # ---- Countdown centraal (col 6 row 0) ---------------------------
        self.lbl_countdown = QLabel("—:—")
        self.lbl_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cd_font = QFont()
        cd_font.setPointSize(56)  # was 88; 72 hoog totaal kan dat niet meer
        cd_font.setBold(True)
        cd_font.setFamily("Consolas, Courier New, monospace")
        self.lbl_countdown.setFont(cd_font)
        self.lbl_countdown.setStyleSheet(f"color: {ACCENT};")
        self.lbl_countdown.setToolTip(
            "Remaining time of the longest-running audio cue. With infinite "
            "loop it counts up (prefix +)."
        )
        self.lbl_countdown.setMinimumWidth(280)
        lay.addWidget(self.lbl_countdown, 0, 6)

        # Col 7 — stretch
        lay.setColumnStretch(7, 1)

        # ---- Naam van de spelende cue rechts (col 8 row 0) --------------
        self.lbl_countdown_name = QLabel("")
        self.lbl_countdown_name.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        name_font = QFont()
        name_font.setPointSize(10)
        self.lbl_countdown_name.setFont(name_font)
        self.lbl_countdown_name.setStyleSheet(f"color: {TEXT_DIM};")
        self.lbl_countdown_name.setMinimumWidth(180)
        lay.addWidget(self.lbl_countdown_name, 0, 8)

        # ---- Refresh-timer voor countdown ----------------------------------
        self._countdown_source = countdown_source
        self._cd_timer = QTimer(self)
        self._cd_timer.setInterval(100)  # 10 Hz is ruim genoeg
        self._cd_timer.timeout.connect(self._refresh_countdown)
        if countdown_source is not None:
            self._cd_timer.start()

    # ---- public API --------------------------------------------------------

    def set_playhead(self, index: int, total: int, cue_label: str = "") -> None:
        if index >= total:
            self.lbl_playhead.setText(f"Playhead: end ({total})")
        else:
            label = f"{index + 1}/{total}"
            if cue_label:
                label += f" — {cue_label}"
            self.lbl_playhead.setText(f"Playhead: {label}")

    def set_active_count(self, n: int) -> None:
        self.lbl_active.setText(f"Active: {n}")

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

    def flash_blocked(self, duration_ms: int = 1500) -> None:
        """Korte rode flash op de showtime-knop wanneer een edit geblockd
        is. Override de globale stylesheet voor `duration_ms`, dan clear
        de override en is de knop weer normaal. Idempotent — een tweede
        call binnen het flash-window restart de timer netjes."""
        self.btn_showtime.setStyleSheet(
            "QPushButton#showtimeButton {"
            "  background: #c0392b;"
            "  color: white;"
            "  border: 2px solid #ff6b5b;"
            "  border-radius: 6px;"
            "}"
        )
        QTimer.singleShot(
            int(max(200, duration_ms)),
            lambda: self.btn_showtime.setStyleSheet(""),
        )

    # ---- countdown ---------------------------------------------------------

    def _refresh_countdown(self) -> None:
        info = self._countdown_source() if self._countdown_source else None
        if info is None:
            self.lbl_countdown.setText("—:—")
            self.lbl_countdown_name.setText("")
            return
        name, seconds, is_countdown = info
        prefix = "" if is_countdown else "+"
        self.lbl_countdown.setText(f"{prefix}{_fmt_time(seconds)}")
        self.lbl_countdown_name.setText(name)
