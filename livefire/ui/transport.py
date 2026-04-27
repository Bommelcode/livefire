"""Transportbalk: GO-knop, Stop All, playhead-indicator, actieve-cue counter,
grote countdown-timer centraal en de spelende cue-naam rechts."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QFrame

from .style import ACCENT, TEXT_DIM


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

    def __init__(self, parent=None, countdown_source: CountdownSource | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        self.btn_go = QPushButton("GO")
        self.btn_go.setObjectName("goButton")
        self.btn_go.setToolTip("Start the cue at the playhead (Space)")
        self.btn_go.clicked.connect(self.go_clicked.emit)
        lay.addWidget(self.btn_go)

        self.btn_stop = QPushButton("Stop All")
        self.btn_stop.setObjectName("stopButton")
        self.btn_stop.setToolTip("Stop all active cues immediately (Escape)")
        self.btn_stop.clicked.connect(self.stop_all_clicked.emit)
        lay.addWidget(self.btn_stop)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(sep)

        self.lbl_playhead = QLabel("Playhead: —")
        self.lbl_playhead.setToolTip("The cue that will fire on the next GO")
        lay.addWidget(self.lbl_playhead)

        self.lbl_active = QLabel("Active: 0")
        self.lbl_active.setToolTip("Number of cues currently playing")
        lay.addWidget(self.lbl_active)

        lay.addStretch(1)

        # ---- Countdown centraal -------------------------------------------
        self.lbl_countdown = QLabel("—:—")
        self.lbl_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cd_font = QFont()
        cd_font.setPointSize(88)
        cd_font.setBold(True)
        cd_font.setFamily("Consolas, Courier New, monospace")
        self.lbl_countdown.setFont(cd_font)
        self.lbl_countdown.setStyleSheet(f"color: {ACCENT};")
        self.lbl_countdown.setToolTip(
            "Remaining time of the longest-running audio cue. With infinite "
            "loop it counts up (prefix +)."
        )
        self.lbl_countdown.setMinimumWidth(360)
        lay.addWidget(self.lbl_countdown)

        lay.addStretch(1)

        # ---- Naam van de spelende cue rechts -----------------------------
        self.lbl_countdown_name = QLabel("")
        self.lbl_countdown_name.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        name_font = QFont()
        name_font.setPointSize(10)
        self.lbl_countdown_name.setFont(name_font)
        self.lbl_countdown_name.setStyleSheet(f"color: {TEXT_DIM};")
        self.lbl_countdown_name.setMinimumWidth(180)
        lay.addWidget(self.lbl_countdown_name)

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
