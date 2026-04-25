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
        "cuetype.Presentation": "Presentatie",
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
        "group.presentation": "Presentatie",
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
    },
    "en": {
        "cuetype.Audio":        "Audio",
        "cuetype.Video":        "Video",
        "cuetype.Presentation": "Presentation",
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
        "group.presentation": "Presentation",
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
    },
}


def set_language(code: str) -> None:
    global LANGUAGE
    LANGUAGE = code if code in _STRINGS else "nl"


def t(key: str) -> str:
    """Lookup. Onbekende sleutel: retourneer 'm zelf zodat ontbrekende
    vertalingen meteen zichtbaar zijn in de UI."""
    return _STRINGS.get(LANGUAGE, _STRINGS["nl"]).get(key, key)
