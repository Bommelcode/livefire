# Changelog

Alle noemenswaardige wijzigingen aan dit project. Format volgens
[Keep a Changelog](https://keepachangelog.com/nl/1.1.0/).

## [0.3.0] — 2026-04-23

### Gewijzigd
- **Project hernoemd van "QCue" naar "liveFire".** Package-naam is nu
  `livefire`, workspace-extensie is `.livefire`. Oude `.qcue`-bestanden
  worden nog niet automatisch herkend — zie migratiepad in v0.3.1.

### Toegevoegd
- Volledige architectuur-refactor van het single-file `qcue.py` uit v0.2.x
  naar een modulaire package (`livefire/cues`, `livefire/engines`,
  `livefire/playback`, `livefire/ui`).
- Nieuwe audio-engine gebaseerd op `sounddevice` + `numpy` als master-mixer,
  met sample-accurate gain-ramps voor Fade-cues.
- Automatische sample-rate conversion via `scipy.signal.resample_poly` voor
  bestanden die niet op de engine-samplerate (48 kHz default) staan.
- Workspace-format v2 met expliciete `format_version` en migratiepad vanaf
  v1 (v0.2.x). Oude `fade_volume_db` wordt automatisch hernoemd naar
  `fade_target_db`.
- Engine-status registry (`livefire.engines.registry`) — iedere engine meldt zijn
  status aan zodat de `Help → Engine-status` dialog en de statusbar altijd
  actueel zijn.
- Testsuite (pytest) voor workspace-roundtrip en migratie.

### Verwijderd
- Pygame-gebaseerde audio-engine (vervangen door sounddevice).
- Video-cue afhankelijkheid van `QtMultimedia` (wordt herwerkt in v0.6.0
  via libVLC + cyndilib).

### Bekende beperkingen
- Multi-output routing en per-cue device-selectie komt in v0.3.1.
- Audio-matrix routing (N-in × M-out) komt in v0.3.2.
- Crossfades tussen twee audio-cues komt in v0.3.x.
- Video-, MIDI-, OSC- en DMX-cues staan op de roadmap maar zijn nog niet
  geïmplementeerd in 0.3.0.

## [0.2.0] — 2026-04 (historisch, als "QCue")

Zie vorige single-file release (`qcue.py`). Bevatte Audio/Video/Group/
Wait/Stop/Fade/Memo/MIDI/OSC/Start cues via pygame.mixer + QtMultimedia.

## [0.1.0] — initial MVP (als "QCue")

Audio/Wait/Stop/Fade/Group/Start/MIDI/OSC/Memo cues via pygame.mixer.
