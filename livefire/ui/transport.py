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
        # Theme-aware layout. Bij constructie lezen we 't actieve theme
        # uit QSettings zodat de transport-widget zich anders kan
        # opbouwen per theme. Switching at runtime requires een
        # restart (Qt-layout is bij __init__ vastgesteld).
        from PyQt6.QtCore import QSettings
        self._theme_id = QSettings().value("ui/theme", "default", type=str)
        # Buitenste VBox met twee/drie secties:
        #   (Cinematic/QLab only) Row 0: enorme volle-breedte countdown
        #   Row 1 (HBox): GO/Stop + Showtime/Inspector + names/timers
        #   Row 2 (HBox): cue-toolbar over de volle breedte
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum,
        )
        outer = QVBoxLayout(self)
        # Padding per theme: Glass + Cinematic willen meer ademruimte.
        if self._theme_id == "glass":
            outer.setContentsMargins(14, 14, 14, 14)
            outer.setSpacing(10)
        elif self._theme_id == "cinematic":
            outer.setContentsMargins(10, 14, 10, 10)
            outer.setSpacing(8)
        elif self._theme_id == "linear":
            outer.setContentsMargins(8, 4, 8, 4)
            outer.setSpacing(2)
        else:
            outer.setContentsMargins(6, 6, 6, 6)
            outer.setSpacing(4)

        # ---- ROW 1 — transport-balk (alle controls + countdown) --------
        # Wrap in 'n widget met max-height = GO/Stop hoogte (80) zodat de
        # rij nooit hoger wordt dan de primaire knoppen. Ook al rendert 'n
        # font groter, de label clipt liever dan dat 't de header strekt.
        row1_widget = QWidget()
        row1_widget.setMaximumHeight(80)
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
        names_col = QVBoxLayout()
        names_col.setContentsMargins(0, 0, 0, 0)
        names_col.setSpacing(2)

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
        row1.addLayout(names_col, 3)

        sep_next_now = QFrame()
        sep_next_now.setFrameShape(QFrame.Shape.VLine)
        sep_next_now.setFrameShadow(QFrame.Shadow.Sunken)
        row1.addWidget(sep_next_now)

        # ---- TIMERS — placement is theme-dependent --------------------
        # Cinematic/QLab krijgen een gigantische REMAIN in een eigen rij
        # boven row1. Andere themes houden 't compact: ELAPSED + REMAIN
        # stacked in de rechter-kolom van row1.
        self._timer_font_pt = 40  # base; resizeEvent past 'm aan
        self._timer_font = QFont("Consolas")
        self._timer_font.setPointSize(self._timer_font_pt)
        self._timer_font.setBold(True)

        TIMER_MIN_W = 140
        # REMAIN — backwards-compat alias 'lbl_countdown'.
        self.lbl_countdown = QLabel("—:—")
        self.lbl_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_countdown.setFont(self._timer_font)
        self.lbl_countdown.setStyleSheet(f"color: {ACCENT};")
        self.lbl_countdown.setToolTip(
            "Remaining time of the longest-running audio cue. With infinite "
            "loop it counts up (prefix +)."
        )
        self.lbl_countdown.setMinimumWidth(TIMER_MIN_W)
        # ELAPSED — kleinere caption.
        self.lbl_elapsed = QLabel("—:—")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_elapsed.setFont(self._timer_font)
        self.lbl_elapsed.setStyleSheet(f"color: {OK};")
        self.lbl_elapsed.setToolTip("Elapsed time of the playing cue")
        self.lbl_elapsed.setMinimumWidth(TIMER_MIN_W)

        if self._theme_id in ("cinematic", "qlab"):
            # Hero countdown: mega-grote REMAIN bovenin, ELAPSED klein
            # eronder maar in de hero-row, niet in row1.
            self._timer_font.setPointSize(80)
            self.lbl_countdown.setFont(self._timer_font)
            hero = QVBoxLayout()
            hero.setContentsMargins(0, 0, 0, 0)
            hero.setSpacing(0)
            hero.addWidget(self.lbl_countdown)
            # ELAPSED klein onder REMAIN — Cinematic/QLab look.
            small = QFont("Consolas")
            small.setPointSize(11)
            self.lbl_elapsed.setFont(small)
            hero.addWidget(self.lbl_elapsed)
            outer.addLayout(hero)
            outer.addWidget(row1_widget)
            # In row1's rechter-kolom blijft 't leeg voor deze themes —
            # niets toevoegen, GO/Stop/names claimen alle ruimte.
            row1.addStretch(1)
        else:
            # Default / Studio / Linear / Glass: ELAPSED + REMAIN stacked
            # in row1's rechter-kolom.
            timers_col = QVBoxLayout()
            timers_col.setContentsMargins(0, 0, 0, 0)
            timers_col.setSpacing(2)
            timers_col.addWidget(self.lbl_elapsed)
            timers_col.addWidget(self.lbl_countdown)
            row1.addLayout(timers_col, 1)
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

        # ---- Theme-specifieke laatste tweaks -----------------------------
        if self._theme_id == "linear":
            # Strak, minimal — verberg de NEXT/NOW PLAYING tegels en
            # vertrouw op de cuelist + countdown alleen.
            self.lbl_playhead.hide()
            self.lbl_countdown_name.hide()

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

        # Cinematic/QLab krijgen een veel grotere countdown-range omdat
        # ze een dedicated hero-row hebben. Andere themes blijven compact.
        if self._theme_id in ("cinematic", "qlab"):
            timer_pt = _scale(48, 100)
        else:
            # Stacked timers in 'n 80-px rij; 22..32 pt is praktisch.
            timer_pt = _scale(22, 32)
        if timer_pt != self._timer_font_pt:
            self._timer_font_pt = timer_pt
            self._timer_font.setPointSize(timer_pt)
            # ELAPSED schaalt niet voor cinematic/qlab — die heeft eigen 11pt.
            if self._theme_id not in ("cinematic", "qlab"):
                self.lbl_elapsed.setFont(self._timer_font)
            self.lbl_countdown.setFont(self._timer_font)
        info_pt = _scale(9, 13)
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
        → off. We gebruiken één persistente QTimer + een step-counter
        i.p.v. vier overlappende singleShots — anders kan een snelle
        herhaling de stijl onbedoeld op rood laten hangen omdat de oude
        en nieuwe lambda's door elkaar fire'n.
        """
        # Bestaande flash interrumperen wanneer we opnieuw worden geroepen.
        if not hasattr(self, "_flash_timer"):
            self._flash_timer = QTimer(self)
            self._flash_timer.setSingleShot(True)
            self._flash_timer.timeout.connect(self._flash_step)
        self._flash_timer.stop()
        self._flash_step_idx = 0
        self._flash_step()

    def _flash_step(self) -> None:
        """Eén stap in de flash-cycle. 0=on,1=off,2=on,3=off,4=eind."""
        cycle = (
            (self._FLASH_STYLE, 200),  # on 200ms
            ("", 180),                 # off 180ms
            (self._FLASH_STYLE, 200),  # on 200ms
            ("", 0),                   # off, einde
        )
        if self._flash_step_idx >= len(cycle):
            return
        style, next_delay = cycle[self._flash_step_idx]
        self.btn_showtime.setStyleSheet(style)
        self._flash_step_idx += 1
        if next_delay > 0:
            self._flash_timer.start(next_delay)

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
