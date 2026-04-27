"""Help → Licentie. Drie blokken:

* **Status** — huidige tier en (indien Pro) de einddatum
* **Aanschaffen** — drie knoppen die naar de koop-URL leiden met de
  gekozen tier als query-param. Na betaling krijgt de gebruiker een
  licentiekey per mail die ze hieronder kunnen plakken.
* **Activeren** — invoerveld voor een licentiekey + Activeer-knop.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QGroupBox, QMessageBox, QFrame,
)

from ... import licensing


_TIER_LABELS = {
    licensing.LicenseTier.DAY:      "1 day",
    licensing.LicenseTier.MONTH:    "1 month",
    licensing.LicenseTier.YEAR:     "1 year",
    licensing.LicenseTier.LIFETIME: "Lifetime (no expiry)",
}


def _fmt_eur(amount: float) -> str:
    return f"€ {amount:.2f}".replace(".", ",")


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("liveFire — License")
        self.setMinimumWidth(480)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # ---- Status -------------------------------------------------------
        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("font-weight: bold; padding: 4px;")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        explainer = QLabel(
            "Audio cues and the organisational types (Wait, Stop, Fade, "
            "Start, Group, Memo) are always free. Video, Image, Presentation "
            "and Network require a Pro license."
        )
        explainer.setWordWrap(True)
        explainer.setStyleSheet("color: palette(mid);")
        lay.addWidget(explainer)

        # ---- Aanschaf-knoppen --------------------------------------------
        buy_grp = QGroupBox("Purchase Pro license")
        buy_lay = QVBoxLayout(buy_grp)
        for tier in (licensing.LicenseTier.DAY,
                     licensing.LicenseTier.MONTH,
                     licensing.LicenseTier.YEAR,
                     licensing.LicenseTier.LIFETIME):
            row = QHBoxLayout()
            label = QLabel(
                f"{_TIER_LABELS[tier]} — {_fmt_eur(licensing.PRICES_EUR[tier])}"
            )
            row.addWidget(label, 1)
            btn = QPushButton("Buy")
            btn.setMinimumWidth(80)
            btn.clicked.connect(lambda _, t=tier: self._open_purchase(t))
            row.addWidget(btn)
            buy_lay.addLayout(row)
        lay.addWidget(buy_grp)

        # ---- Activeren ----------------------------------------------------
        act_grp = QGroupBox("Activate license key")
        act_lay = QVBoxLayout(act_grp)
        act_lay.addWidget(QLabel(
            "Paste the key you received by email after purchase."
        ))
        row = QHBoxLayout()
        self.ed_key = QLineEdit()
        self.ed_key.setPlaceholderText("LF-MONTH-2026-12-31-A1B2C3D4")
        row.addWidget(self.ed_key, 1)
        self.btn_activate = QPushButton("Activate")
        self.btn_activate.clicked.connect(self._activate)
        row.addWidget(self.btn_activate)
        act_lay.addLayout(row)
        lay.addWidget(act_grp)

        # Deactiveer-knop (alleen zichtbaar als er een Pro-licentie is)
        self.btn_deactivate = QPushButton("Remove license")
        self.btn_deactivate.setFlat(True)
        self.btn_deactivate.clicked.connect(self._deactivate)
        deact_row = QHBoxLayout()
        deact_row.addStretch(1)
        deact_row.addWidget(self.btn_deactivate)
        lay.addLayout(deact_row)

        # ---- Sluiten ------------------------------------------------------
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        self._refresh_status()
        # Houd in sync als andere code-paden de licentie wijzigen.
        licensing.signaler.license_changed.connect(self._refresh_status)

    # ---- internals ---------------------------------------------------------

    def _refresh_status(self) -> None:
        self.lbl_status.setText("Status: " + licensing.status_summary())
        self.btn_deactivate.setVisible(licensing.is_pro())

    def _open_purchase(self, tier: str) -> None:
        url = QUrl(f"{licensing.PURCHASE_URL}?tier={tier.lower()}")
        QDesktopServices.openUrl(url)

    def _activate(self) -> None:
        key = self.ed_key.text().strip()
        if not key:
            return
        ok, msg = licensing.activate(key)
        if ok:
            QMessageBox.information(self, "Activation successful", msg)
            self.ed_key.clear()
        else:
            QMessageBox.warning(self, "Activation failed", msg)
        self._refresh_status()

    def _deactivate(self) -> None:
        r = QMessageBox.question(
            self, "Remove license",
            "Are you sure you want to remove your current license? "
            "You can re-activate it later with the same key, as long as it "
            "hasn't expired.",
        )
        if r == QMessageBox.StandardButton.Yes:
            licensing.deactivate()
            self._refresh_status()
