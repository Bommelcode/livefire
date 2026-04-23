"""Transportbalk: GO-knop, Stop All, playhead-indicator, actieve-cue counter."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QFrame


class TransportWidget(QWidget):
    go_clicked = pyqtSignal()
    stop_all_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        self.btn_go = QPushButton("GO")
        self.btn_go.setObjectName("goButton")
        self.btn_go.clicked.connect(self.go_clicked.emit)
        lay.addWidget(self.btn_go)

        self.btn_stop = QPushButton("Stop All")
        self.btn_stop.setObjectName("stopButton")
        self.btn_stop.clicked.connect(self.stop_all_clicked.emit)
        lay.addWidget(self.btn_stop)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(sep)

        self.lbl_playhead = QLabel("Playhead: —")
        lay.addWidget(self.lbl_playhead)

        self.lbl_active = QLabel("Actief: 0")
        lay.addWidget(self.lbl_active)

        lay.addStretch(1)

    def set_playhead(self, index: int, total: int, cue_label: str = "") -> None:
        if index >= total:
            self.lbl_playhead.setText(f"Playhead: einde ({total})")
        else:
            label = f"{index + 1}/{total}"
            if cue_label:
                label += f" — {cue_label}"
            self.lbl_playhead.setText(f"Playhead: {label}")

    def set_active_count(self, n: int) -> None:
        self.lbl_active.setText(f"Actief: {n}")
