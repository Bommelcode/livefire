"""Dialog die alle geregistreerde engines + status toont."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton, QHBoxLayout,
)

from ...engines import registry


class EngineStatusDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Engine-status")
        self.resize(520, 340)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Overzicht van playback-engines. Wat niet beschikbaar is, "
            "wordt hier met foutmelding getoond."
        ))

        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        lay.addWidget(self.txt)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_close = QPushButton("Sluiten")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        lay.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        lines: list[str] = []
        for s in registry.all_statuses():
            mark = "✓" if s.available else "✗"
            lines.append(f"{mark}  {s.name}")
            if s.detail:
                for subline in s.detail.splitlines():
                    lines.append(f"     {subline}")
            lines.append("")
        if not lines:
            lines = ["Geen engines geregistreerd."]
        self.txt.setPlainText("\n".join(lines))
