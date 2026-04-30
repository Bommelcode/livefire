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
    # Operator wisselt de inspector-zichtbaarheid via de transport-knop.
    # MainWindow connect 'm aan een slot dat self.inspector.setVisible() doet.
    inspector_toggled = pyqtSignal(bool)

    def __init__(self, parent=None, countdown_source: CountdownSource | None = None):
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
        self._icon_lock_closed = (
            QIcon(str(_ICON_LOCK_CLOSED)) if _ICON_LOCK_CLOSED.is_file() else QIcon()
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

        self.lbl_playhead = QLabel("Playhead: —")
        self.lbl_playhead.setToolTip("The cue that will fire on the next GO")
        row1.addWidget(self.lbl_playhead)

        self.lbl_active = QLabel("Active: 0")
        self.lbl_active.setToolTip("Number of cues currently playing")
        row1.addWidget(self.lbl_active)

        self.lbl_countdown = QLabel("—:—")
        self.lbl_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cd_font = QFont()
        cd_font.setPointSize(56)
        cd_font.setBold(True)
        cd_font.setFamily("Consolas, Courier New, monospace")
        self.lbl_countdown.setFont(cd_font)
        self.lbl_countdown.setStyleSheet(f"color: {ACCENT};")
        self.lbl_countdown.setToolTip(
            "Remaining time of the longest-running audio cue. With infinite "
            "loop it counts up (prefix +)."
        )
        # Geen vaste min-width — laat 'm krimpen wanneer 't venster smal is.
        # Boven 't auto-shrink-pad past 'ie wel de 56 pt-font zelf aan.
        self.lbl_countdown.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        row1.addWidget(self.lbl_countdown, 2)  # stretch=2 → claimt 't centrum

        self.lbl_countdown_name = QLabel("")
        self.lbl_countdown_name.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        name_font = QFont()
        name_font.setPointSize(10)
        self.lbl_countdown_name.setFont(name_font)
        self.lbl_countdown_name.setStyleSheet(f"color: {TEXT_DIM};")
        # Idem: laat de naam krimpen i.p.v. 'n vaste 180 px af te dwingen.
        self.lbl_countdown_name.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        row1.addWidget(self.lbl_countdown_name, 1)

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
