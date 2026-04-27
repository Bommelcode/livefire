"""Dialog die bij drag-drop van een PowerPoint-bestand vraagt hoe het
moet worden toegevoegd:

* **slides** — exporteer iedere slide naar PNG via PowerPoint COM en
               plaats één Afbeelding-cue per slide. Daarna is PowerPoint
               niet meer nodig om de show te draaien.
* **single** — één Presentatie-cue (Open). PowerPoint blijft de speler;
               volgende/vorige slide regel je met aparte cues.

Voor `.pptx`/`.pptm` weten we het slide-aantal vooraf via een ZIP-XML-
telling (zie ``engines.powerpoint.count_slides``), zodat de dialog dat
kan tonen voordat er iets aan PowerPoint wordt gevraagd. Voor `.ppt`
(legacy binary) is het aantal pas bekend tijdens de export.

Als PowerPoint COM niet beschikbaar is (geen Office of niet-Windows)
wordt de slides-optie uitgeschakeld — exporteren kan alleen via COM.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QPushButton, QButtonGroup, QFrame, QCheckBox,
)

from ...i18n import t
from ..style import TEXT_DIM


# Resultaat-keuzes
MODE_SLIDES = "slides"
MODE_SINGLE = "single"


class PptImportDialog(QDialog):
    """Vraag de gebruiker hoe een PowerPoint-bestand toegevoegd moet worden."""

    def __init__(
        self,
        file_path: str,
        slide_count: int | None,
        *,
        com_available: bool = True,
        show_apply_to_all: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._file_path = file_path
        self._slide_count = slide_count

        self.setWindowTitle(t("pptimport.title"))
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Bestandsnaam + vraag
        fname = Path(file_path).name
        lay.addWidget(QLabel(f"<b>{fname}</b>"))
        lay.addWidget(QLabel(t("pptimport.question")))

        # Optie 1 — slides als ingebedde afbeeldingen
        self.rb_slides = QRadioButton(t("pptimport.opt_slides"))
        self.rb_slides.setEnabled(com_available)
        lay.addWidget(self.rb_slides)

        if slide_count is not None:
            desc1 = t("pptimport.opt_slides_desc_n").format(n=slide_count)
        else:
            desc1 = t("pptimport.opt_slides_desc_unknown")
        if not com_available:
            desc1 = desc1 + "\n\n⚠ " + t("pptimport.opt_slides_unavailable")
        lbl_desc1 = QLabel(desc1)
        lbl_desc1.setWordWrap(True)
        lbl_desc1.setStyleSheet(f"color: {TEXT_DIM}; padding-left: 22px;")
        lay.addWidget(lbl_desc1)

        # Scheiding
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(line)

        # Optie 2 — single Presentation-cue
        self.rb_single = QRadioButton(t("pptimport.opt_single"))
        lay.addWidget(self.rb_single)

        lbl_desc2 = QLabel(t("pptimport.opt_single_desc"))
        lbl_desc2.setWordWrap(True)
        lbl_desc2.setStyleSheet(f"color: {TEXT_DIM}; padding-left: 22px;")
        lay.addWidget(lbl_desc2)

        # Default-keuze: slides als COM beschikbaar is, anders single.
        if com_available:
            self.rb_slides.setChecked(True)
        else:
            self.rb_single.setChecked(True)

        self._group = QButtonGroup(self)
        self._group.addButton(self.rb_slides)
        self._group.addButton(self.rb_single)

        # Optionele checkbox bij multi-PPT-drop
        self.cb_apply_all: QCheckBox | None = None
        if show_apply_to_all:
            line2 = QFrame()
            line2.setFrameShape(QFrame.Shape.HLine)
            line2.setFrameShadow(QFrame.Shadow.Sunken)
            lay.addWidget(line2)
            self.cb_apply_all = QCheckBox(t("pptimport.apply_to_all"))
            self.cb_apply_all.setChecked(True)
            lay.addWidget(self.cb_apply_all)

        # Knoppen
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton(t("btn.cancel"))
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(t("btn.ok"))
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    # ---- public API --------------------------------------------------------

    def chosen_mode(self) -> str:
        return MODE_SLIDES if self.rb_slides.isChecked() else MODE_SINGLE

    def apply_to_all(self) -> bool:
        return self.cb_apply_all is not None and self.cb_apply_all.isChecked()
