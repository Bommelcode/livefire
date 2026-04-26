"""Lichte i18n-laag. Geen Qt-tr() / .ts-bestanden — voor één applicatie
met twee talen is een dict-lookup pragmatischer en code-review-bestendig.

Gebruik:
    from .i18n import t
    label = t("cuetype.video")        # → "Video"

De huidige taal is een module-level global; bij start lees je 'm uit
QSettings en zet je 'm met set_language(). Wijzigingen tijdens de
sessie vereisen een app-herstart om consistent door alle bestaande
widgets te flowen — daar voorkomen we Qt's signal-spam mee.
"""

from __future__ import annotations

LANGUAGE: str = "nl"

# Talen die in de UI keuzelijst verschijnen.
SUPPORTED: list[tuple[str, str]] = [
    ("nl", "Nederlands"),
    ("en", "English"),
]

_STRINGS: dict[str, dict[str, str]] = {
    "nl": {
        # Cue-types (display-labels — de Python-constanten blijven hetzelfde
        # voor JSON-stabiliteit van workspaces).
        "cuetype.Audio":        "Audio",
        "cuetype.Video":        "Video",
        "cuetype.Image":        "Afbeelding",
        "cuetype.Presentation": "Presentatie",
        "cuetype.Network":      "Network",
        "cuetype.Group":        "Groep",
        "cuetype.Wait":         "Wacht",
        "cuetype.Stop":         "Stop",
        "cuetype.Fade":         "Fade",
        "cuetype.Memo":         "Memo",
        "cuetype.Start":        "Start",
        # Continue-modes
        "continue.do_not":         "Niet doorgaan",
        "continue.auto_continue":  "Auto-doorgaan",
        "continue.auto_follow":    "Auto-volgen",
        # Cue-states
        "state.idle":     "wacht",
        "state.running":  "actief",
        "state.finished": "klaar",
        # Cuelist-kolomtitels
        "col.nr":       "Nr",
        "col.type":     "Type",
        "col.name":     "Naam",
        "col.duration": "Duur",
        "col.continue": "Continue",
        "col.state":    "Status",
        # Inspector-groep titels
        "group.general":      "Algemeen",
        "group.timing":       "Timing",
        "group.audio":        "Audio",
        "group.video":        "Video",
        "group.image":        "Afbeelding",
        "group.presentation": "Presentatie",
        "group.network":      "Network (OSC-out)",
        "group.wait":         "Wacht",
        "group.target":       "Doel",
        "group.triggers":     "Triggers",
        "group.notes":        "Notities",
        # Menu's
        "menu.file":      "&Bestand",
        "menu.cue":       "&Cue",
        "menu.transport": "&Transport",
        "menu.help":      "&Help",
        # Algemene knoppen
        "btn.close":  "Sluiten",
        "btn.cancel": "Annuleren",
        "btn.ok":     "OK",
        "btn.delete": "Verwijderen",
        "btn.renumber": "Hernummeren",
        # Voorkeuren — taal-veld
        "prefs.language":         "Taal",
        "prefs.language.tooltip":
            "Taal van de interface. Wijziging treedt in werking na "
            "herstart van liveFire.",
        "prefs.language.restart_title": "Herstart vereist",
        "prefs.language.restart_body":
            "De taalwijziging wordt actief na een herstart van liveFire.",
        # PPT-import dialog (v0.4.1)
        "pptimport.title":            "PowerPoint toevoegen",
        "pptimport.question":         "Hoe wil je deze toevoegen?",
        "pptimport.opt_slides":       "Slides als ingebedde afbeeldingen",
        "pptimport.opt_slides_desc_n":
            "Exporteert {n} slides naar PNG en plaatst één Afbeelding-cue "
            "per slide. PowerPoint is daarna niet meer nodig om de show "
            "te draaien.",
        "pptimport.opt_slides_desc_unknown":
            "Exporteert iedere slide naar PNG en plaatst één Afbeelding-"
            "cue per slide. PowerPoint is daarna niet meer nodig om de "
            "show te draaien.",
        "pptimport.opt_slides_unavailable":
            "Vereist Microsoft PowerPoint op deze machine om de slides "
            "te kunnen exporteren.",
        "pptimport.opt_single":       "Eén Presentatie-cue",
        "pptimport.opt_single_desc":
            "Opent de show in PowerPoint; volgende/vorige slide regel je "
            "via aparte cues.",
        "pptimport.slide_count_label": "Aantal slides:",
        "pptimport.apply_to_all":      "Toepassen op alle PPTs in deze drop",
        "pptimport.exporting_title":   "Slides exporteren",
        "pptimport.exporting_label":   "Slide {i} van {n}…",
        "pptimport.export_failed":     "Slide-export mislukt",
        # Network test-send knop
        "btn.test_send":      "Test verzenden",
        "btn.test_send.done": "Verzonden ✓",
    },
    "en": {
        "cuetype.Audio":        "Audio",
        "cuetype.Video":        "Video",
        "cuetype.Image":        "Image",
        "cuetype.Presentation": "Presentation",
        "cuetype.Network":      "Network",
        "cuetype.Group":        "Group",
        "cuetype.Wait":         "Wait",
        "cuetype.Stop":         "Stop",
        "cuetype.Fade":         "Fade",
        "cuetype.Memo":         "Memo",
        "cuetype.Start":        "Start",
        "continue.do_not":         "Do Not Continue",
        "continue.auto_continue":  "Auto-Continue",
        "continue.auto_follow":    "Auto-Follow",
        "state.idle":     "idle",
        "state.running":  "running",
        "state.finished": "finished",
        "col.nr":       "Nr",
        "col.type":     "Type",
        "col.name":     "Name",
        "col.duration": "Duration",
        "col.continue": "Continue",
        "col.state":    "State",
        "group.general":      "General",
        "group.timing":       "Timing",
        "group.audio":        "Audio",
        "group.video":        "Video",
        "group.image":        "Image",
        "group.presentation": "Presentation",
        "group.network":      "Network (OSC-out)",
        "group.wait":         "Wait",
        "group.target":       "Target",
        "group.triggers":     "Triggers",
        "group.notes":        "Notes",
        "menu.file":      "&File",
        "menu.cue":       "&Cue",
        "menu.transport": "&Transport",
        "menu.help":      "&Help",
        "btn.close":  "Close",
        "btn.cancel": "Cancel",
        "btn.ok":     "OK",
        "btn.delete": "Delete",
        "btn.renumber": "Renumber",
        "prefs.language":         "Language",
        "prefs.language.tooltip":
            "Interface language. Change takes effect after restarting "
            "liveFire.",
        "prefs.language.restart_title": "Restart required",
        "prefs.language.restart_body":
            "The language change takes effect after restarting liveFire.",
        # PPT-import dialog (v0.4.1)
        "pptimport.title":            "Add PowerPoint",
        "pptimport.question":         "How would you like to add this?",
        "pptimport.opt_slides":       "Slides as embedded images",
        "pptimport.opt_slides_desc_n":
            "Exports {n} slides to PNG and inserts one Image cue per "
            "slide. PowerPoint is no longer needed to run the show.",
        "pptimport.opt_slides_desc_unknown":
            "Exports each slide to PNG and inserts one Image cue per "
            "slide. PowerPoint is no longer needed to run the show.",
        "pptimport.opt_slides_unavailable":
            "Requires Microsoft PowerPoint on this machine to export "
            "the slides.",
        "pptimport.opt_single":       "Single Presentation cue",
        "pptimport.opt_single_desc":
            "Opens the show in PowerPoint; next/previous slide is handled "
            "by separate cues.",
        "pptimport.slide_count_label": "Slide count:",
        "pptimport.apply_to_all":      "Apply to all PPTs in this drop",
        "pptimport.exporting_title":   "Exporting slides",
        "pptimport.exporting_label":   "Slide {i} of {n}…",
        "pptimport.export_failed":     "Slide export failed",
        # Network test-send knop
        "btn.test_send":      "Test send",
        "btn.test_send.done": "Sent ✓",
    },
}


def set_language(code: str) -> None:
    global LANGUAGE
    LANGUAGE = code if code in _STRINGS else "nl"


def t(key: str) -> str:
    """Lookup. Onbekende sleutel: retourneer 'm zelf zodat ontbrekende
    vertalingen meteen zichtbaar zijn in de UI."""
    return _STRINGS.get(LANGUAGE, _STRINGS["nl"]).get(key, key)
