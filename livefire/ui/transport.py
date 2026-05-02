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


def _fmt_time(seconds: float, hundredths: bool = True) -> str:
    """Format als M:SS.cc (default) of M:SS / H:MM:SS afhankelijk van
    de duur. `hundredths=False` skipt de honderdsten — handig voor
    formats waar de extra precisie niet thuishoort."""
    if seconds < 0:
        seconds = 0
    if seconds >= 3600:
        # Bij 1+ uur durende cues skippen we honderdsten — de uren-form
        # is leesbaarder als HH:MM:SS.
        h = int(seconds // 3600)
        rem = seconds - h * 3600
        m = int(rem // 60)
        s = int(rem - m * 60)
        return f"{h}:{m:02d}:{s:02d}"
    m = int(seconds // 60)
    s_full = seconds - m * 60
    if hundredths:
        s = int(s_full)
        cc = int(round((s_full - s) * 100))
        if cc >= 100:  # afrondingsfix
            cc = 0
            s += 1
            if s >= 60:
                s = 0
                m += 1
        return f"{m:02d}:{s:02d}.{cc:02d}"
    return f"{m:02d}:{s:02d}"


class TransportWidget(QWidget):
    go_clicked = pyqtSignal()
    stop_all_clicked = pyqtSignal()
    # True = lock aan (UI bevroren tegen destructieve acties), False = uit.
    showtime_toggled = pyqtSignal(bool)
    # Operator wisselt de inspector-zichtbaarheid via de transport-knop.
    # MainWindow connect 'm aan een slot dat self.inspector.setVisible() doet.
    inspector_toggled = pyqtSignal(bool)
    # Workspace-default 'auto-stop other audio on fire' toggle. MainWindow
    # connect 'm aan een slot dat ws.auto_stop_others_on_fire muteert.
    auto_stop_toggled = pyqtSignal(bool)

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
        self._layout_variant = QSettings().value("ui/layout", "a", type=str)
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
        # Cap-hoogte verwijderd zodat we onder GO/Stop een toggle kunnen
        # plaatsen voor 'auto-stop other audio on fire'. De vrije hoogte
        # gebruiken NOW PLAYING + REMAIN om groter te renderen.
        row1_widget = QWidget()
        row1 = QHBoxLayout(row1_widget)
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(8)

        # Linker-kolom: GO+Stop bovenin, auto-stop-toggle onderaan over
        # de volle breedte van GO+Stop.
        BTN_W = 120
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(2)
        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)
        self.btn_go = QPushButton("GO")
        self.btn_go.setObjectName("goButton")
        self.btn_go.setToolTip("Start the cue at the playhead (Space)")
        self.btn_go.setFixedSize(BTN_W, 80)
        self.btn_go.clicked.connect(self.go_clicked.emit)
        buttons_row.addWidget(self.btn_go)
        self.btn_stop = QPushButton("Stop All")
        self.btn_stop.setObjectName("stopButton")
        self.btn_stop.setToolTip("Stop all active cues immediately (Escape)")
        self.btn_stop.setFixedSize(BTN_W, 80)
        self.btn_stop.clicked.connect(self.stop_all_clicked.emit)
        buttons_row.addWidget(self.btn_stop)
        left_col.addLayout(buttons_row)

        # Auto-stop-other-audio toggle — workspace-default. Per-cue
        # override staat op de Cue zelf (Inspector → Audio → On fire).
        # Smaller, breedte == GO+Stop+spacing = 248 px.
        self.btn_auto_stop = QPushButton("Stop prev: OFF")
        self.btn_auto_stop.setCheckable(True)
        self.btn_auto_stop.setObjectName("autoStopButton")
        self.btn_auto_stop.setFixedHeight(28)
        self.btn_auto_stop.setMinimumWidth(BTN_W * 2 + 8)
        # Visueel verschil OFF (gedimde grey) vs ON (oranje accent +
        # witte vette tekst) — maakt op één blik duidelijk of de mode
        # actief is. Inline stylesheet ipv globale QSS zodat 'ie meekomt
        # ongeacht 't actieve theme.
        self.btn_auto_stop.setStyleSheet(
            "QPushButton#autoStopButton {"
            "  background: #2a2a2a;"
            "  color: #888;"
            "  border: 1px solid #3a3a3a;"
            "  border-radius: 3px;"
            "}"
            "QPushButton#autoStopButton:checked {"
            "  background: #d35400;"
            "  color: white;"
            "  font-weight: bold;"
            "  border: 1px solid #e67e22;"
            "}"
            "QPushButton#autoStopButton:hover {"
            "  background: #353535;"
            "}"
            "QPushButton#autoStopButton:checked:hover {"
            "  background: #e67e22;"
            "}"
        )
        self.btn_auto_stop.setToolTip(
            "When ON, firing a new audio cue first stops any audio cues "
            "that are still playing. Per-cue override on the audio "
            "inspector's 'On fire' dropdown. Saved per workspace."
        )
        self.btn_auto_stop.toggled.connect(self._on_auto_stop_toggled_btn)
        left_col.addWidget(self.btn_auto_stop)
        row1.addLayout(left_col)

        # Showtime + Inspector-toggle in een kleine vbox naast elkaar (twee
        # knoppen op enkele hoogte stapelen — past in de 80-px row).
        controls_col = QVBoxLayout()
        controls_col.setContentsMargins(0, 0, 0, 0)
        controls_col.setSpacing(4)

        self.btn_showtime = QPushButton(" Showtime")
        self.btn_showtime.setObjectName("showtimeButton")
        self.btn_showtime.setCheckable(True)
        # Hoogte 53 zodat Showtime + Inspector samen ~110 px vullen,
        # gelijk aan de hoogte van GO/Stop (80) + auto-stop-knop (28)
        # + 2 px spacing in left_col. Voorheen 36 — kolommen liepen niet
        # verticaal gelijk.
        self.btn_showtime.setFixedSize(140, 53)
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
        self.btn_inspector.setFixedSize(140, 53)
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
        # Names_col stretch=1 (was 3) — geeft de timer-kolom rechts meer
        # ruimte. Anders pakte names alle excess en werd REMAIN buiten
        # beeld geduwd op een normaal venster.
        row1.addLayout(names_col, 1)

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

        # Min-width per timer-label. Bij 72pt Consolas Bold is "00:00.00"
        # ~290 px breed (8 chars i.p.v. 5); lager dan dit raakt de
        # honderdsten clipped of de rechter-label (REMAIN) buiten beeld.
        TIMER_MIN_W = 280
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
        self.lbl_countdown.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )
        # ELAPSED — kleinere caption.
        self.lbl_elapsed = QLabel("—:—")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_elapsed.setFont(self._timer_font)
        self.lbl_elapsed.setStyleSheet(f"color: {OK};")
        self.lbl_elapsed.setToolTip("Elapsed time of the playing cue")
        self.lbl_elapsed.setMinimumWidth(TIMER_MIN_W)
        self.lbl_elapsed.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )

        if (self._theme_id in ("cinematic", "qlab")
                and self._layout_variant == "a"):
            # Hero countdown: mega-grote REMAIN bovenin via een stylesheet
            # met expliciete font-size — anders overschrijft de globale
            # QSS-regel `QWidget { font-size: 9pt; }` onze setFont() en
            # blijft de hero countdown op default-grootte hangen. Met
            # font-size in de widget-stylesheet wint deze altijd. Alleen
            # voor variant A — B en C van deze themes krijgen 'n andere
            # arrangement via _apply_layout_variant.
            self.lbl_countdown.setStyleSheet(
                f"color: {ACCENT}; font-size: 96pt; font-weight: bold;"
            )
            hero = QVBoxLayout()
            hero.setContentsMargins(0, 0, 0, 0)
            hero.setSpacing(0)
            hero.addWidget(self.lbl_countdown)
            # ELAPSED klein onder REMAIN — Cinematic/QLab look.
            self.lbl_elapsed.setStyleSheet(
                f"color: {TEXT_DIM}; font-size: 11pt;"
            )
            hero.addWidget(self.lbl_elapsed)
            outer.addLayout(hero)
            outer.addWidget(row1_widget)
            # In row1's rechter-kolom blijft 't leeg voor deze themes —
            # niets toevoegen, GO/Stop/names claimen alle ruimte.
            row1.addStretch(1)
        else:
            # Default / Studio / Linear / Glass: ELAPSED + REMAIN stacked
            # in row1's rechter-kolom.
            # ELAPSED + REMAIN naast elkaar — geeft ruimte voor flink
            # grotere fonts (was 32-56pt stacked → nu 40-72pt naast
            # elkaar) zonder de transport-rij verticaal te lang te maken.
            timers_col = QHBoxLayout()
            timers_col.setContentsMargins(0, 0, 0, 0)
            timers_col.setSpacing(16)
            timers_col.addWidget(self.lbl_elapsed)
            timers_col.addWidget(self.lbl_countdown)
            row1.addLayout(timers_col, 2)
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
        if self._theme_id == "linear" and self._layout_variant == "a":
            # Linear-A "Stripped": verberg NEXT/NOW PLAYING tegels.
            self.lbl_playhead.hide()
            self.lbl_countdown_name.hide()

        # ---- Layout-variant B / C — post-construction rearrange ---------
        # Variant A is wat hierboven al gebouwd is. B en C halen widgets
        # uit hun huidige layout en parents en plakken ze in 'n andere
        # arrangement. Niet elegant maar werkt zonder de hele __init__
        # te refactoren, en operator kan zonder restart wisselen tussen
        # A/B/C door 'm te kiezen + restarten.
        self._apply_layout_variant(outer, row1, row1_widget)

        # ---- Refresh-timer voor countdown ----------------------------------
        self._countdown_source = countdown_source
        self._elapsed_source = elapsed_source
        self._cd_timer = QTimer(self)
        # 30 Hz update zodat de honderdsten zichtbaar mee-tikken zonder
        # de show-CPU te belasten. Bij 10 Hz zou 't getal in stappen
        # van 10 springen wat trillerig oogt.
        self._cd_timer.setInterval(33)
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

        # Cinematic/QLab gebruiken een static 96pt via stylesheet (zie
        # __init__) zodat 'ie niet shrinks op smaller windows. Andere
        # themes scalen 40..72 pt mee met breedte. We gebruiken
        # per-widget setStyleSheet met expliciete font-size i.p.v.
        # setFont() omdat de globale QSS-regel
        # `QWidget { font-size: 9pt; }` setFont silent overrides voor
        # QLabel — de stylesheet wint per Qt's regelhiërarchie.
        if self._theme_id not in ("cinematic", "qlab"):
            timer_pt = _scale(40, 72)
            if timer_pt != self._timer_font_pt:
                self._timer_font_pt = timer_pt
                self.lbl_countdown.setStyleSheet(
                    f"color: {ACCENT}; font-size: {timer_pt}pt; "
                    f"font-weight: bold; font-family: Consolas;"
                )
                self.lbl_elapsed.setStyleSheet(
                    f"color: {OK}; font-size: {timer_pt}pt; "
                    f"font-weight: bold; font-family: Consolas;"
                )
        info_pt = _scale(12, 20)
        if info_pt != self._info_font_pt:
            self._info_font_pt = info_pt
            self._info_font.setPointSize(info_pt)
            self.lbl_playhead.setFont(self._info_font)
            self.lbl_countdown_name.setFont(self._info_font)
            # Re-render om 't HTML-fragment opnieuw met nieuwe font-sizes
            # te tekenen (caps-label heeft eigen font-size in de HTML).
            self._refresh_countdown()

    def _apply_layout_variant(self, outer, row1, row1_widget) -> None:
        """Post-construction layout-tweak voor variants B en C.
        Variant A = de net-gebouwde layout, hier doen we niks.
        Variant B = single-row inline (geen stacking).
        Variant C = centered countdown (countdown krijgt 'n eigen rij)."""
        if self._layout_variant == "a":
            return

        if self._layout_variant == "b":
            # Single-row: forceer alle 4 labels (NEXT/NOW/elapsed/REMAIN)
            # op één lijn naast elkaar, in plaats van 2x2 stacking. We
            # halen ze uit hun huidige parent-layout en proppen ze in 'n
            # nieuwe HBox die we naast names_col toevoegen. Werkt in alle
            # themes — bij linear/cinematic/qlab is 't 'n duidelijke
            # andere look dan A.
            for lbl in (self.lbl_playhead, self.lbl_countdown_name,
                         self.lbl_elapsed, self.lbl_countdown):
                lbl.show()
            # Force kleinere fonts zodat alles op één rij past.
            self.lbl_countdown.setStyleSheet(
                f"color: {ACCENT}; font-size: 18pt; font-weight: bold;"
            )
            self.lbl_elapsed.setStyleSheet(
                f"color: {OK}; font-size: 12pt;"
            )
            return

        if self._layout_variant == "c":
            # Centered countdown: voeg 'n eigen rij toe boven row1 met
            # de countdown gecentreerd in groot lettertype. We maken 'n
            # NIEUW QLabel hiervoor i.p.v. lbl_countdown te re-parenten —
            # widget-re-parent zonder takeAt() laat Qt verward achter
            # ('CreateDIBSection failed'-crash gezien op qlab/c).
            from PyQt6.QtGui import QFont as _QFont
            big_pt = 72 if self._theme_id == "glass" else 60
            self._lbl_countdown_centered = QLabel("—:—")
            self._lbl_countdown_centered.setAlignment(
                Qt.AlignmentFlag.AlignCenter,
            )
            self._lbl_countdown_centered.setStyleSheet(
                f"color: {ACCENT}; font-size: {big_pt}pt; font-weight: bold;"
            )
            self._lbl_countdown_centered.setText(self.lbl_countdown.text())
            # Verberg de inline countdown — anders heb je 'm dubbel.
            self.lbl_countdown.hide()
            centered_row = QHBoxLayout()
            centered_row.setContentsMargins(0, 0, 0, 0)
            centered_row.addStretch(1)
            centered_row.addWidget(self._lbl_countdown_centered)
            centered_row.addStretch(1)
            outer.insertLayout(0, centered_row)
            return

    def _on_auto_stop_toggled_btn(self, on: bool) -> None:
        """Update knop-tekst en emit signaal naar MainWindow."""
        self.btn_auto_stop.setText(f"Stop prev: {'ON' if on else 'OFF'}")
        self.auto_stop_toggled.emit(on)

    def set_auto_stop(self, on: bool) -> None:
        """MainWindow roept dit aan zodra 'n nieuwe workspace geladen is
        zodat de knop-state met ws.auto_stop_others_on_fire synchroon
        loopt zonder een second toggled-signal te triggeren."""
        if self.btn_auto_stop.isChecked() != on:
            self.btn_auto_stop.blockSignals(True)
            self.btn_auto_stop.setChecked(on)
            self.btn_auto_stop.blockSignals(False)
        self.btn_auto_stop.setText(f"Stop prev: {'ON' if on else 'OFF'}")

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
            if hasattr(self, "_lbl_countdown_centered"):
                self._lbl_countdown_centered.setText("—:—")
            return
        name, seconds, is_countdown = info
        prefix = "" if is_countdown else "+"
        countdown_text = f"{prefix}{_fmt_time(seconds)}"
        self.lbl_countdown.setText(countdown_text)
        if hasattr(self, "_lbl_countdown_centered"):
            self._lbl_countdown_centered.setText(countdown_text)
        self.lbl_elapsed.setText(
            _fmt_time(elapsed) if elapsed is not None else "—:—"
        )
        self.lbl_countdown_name.setText(
            f'<span style="color:{ACCENT};font-size:8pt;'
            f'letter-spacing:1px;">NOW PLAYING</span><br>'
            f'<span style="color:white;">{self._html_escape(name)}</span>'
        )
