# Changelog

Alle noemenswaardige wijzigingen aan dit project. Format volgens
[Keep a Changelog](https://keepachangelog.com/nl/1.1.0/).

## [Unreleased]

### Toegevoegd
- **Volume-veld op Video-cues** in de inspector (−96..0 dB, geen boost
  omdat libVLC's audio_set_volume daar boven afkapt). Hergebruikt het
  bestaande `volume_db`-veld zodat audio en video dezelfde dB-range
  delen en de workspace zonder migratie compatibel blijft. dB →
  0..100% lineaire amplitude, gezet vóór `play()` op de player.

### Verholpen
- Geen UI-flits meer tussen twee opeenvolgende video-cues bij
  AUTO_FOLLOW. De oude `VideoWindow` wordt eerst gepauzeerd (laatste
  frame blijft staan) en pas 300 ms later geclosed/released, zodat de
  volgende videowindow er bovenop kan komen voordat de oude verdwijnt.

### Toegevoegd
- **Trim** (in/uit-punt) op Video-cues. De inspector toont een
  preview-widget met VLC-thumbnail en sleepbare tijdlijn-markers; daarnaast
  spinboxen voor numerieke invoer. Beide paden syncen bidirectioneel en
  scrubben de preview live mee. Trim wordt aan libVLC doorgegeven via
  `:start-time` / `:stop-time`; de Duur-kolom in de cuelist en de
  countdown respecteren het getrimde eind. Workspace bewaart
  `video_start_offset`, `video_end_offset` en een gecachte
  `video_file_duration`.
- **OSC-input** voor cue-triggering vanaf Companion / Stream Deck / externe
  consoles. Elke cue krijgt een optioneel `trigger_osc` veld (bv.
  `/livefire/go/intro`); inkomende OSC-messages met dezelfde address vuren
  de cue af via `PlaybackController.fire_cue()`. UDP-poort en enable-flag
  zijn instelbaar via Voorkeuren (standaard 53000, default uit). Nieuwe
  `OscInputEngine` draait in een daemon-thread met een Qt-signal zodat
  de UI-thread de messages netjes opvangt.
- "Learn…"-knop in de inspector bij het OSC-trigger-veld: wacht op de
  eerstvolgende OSC-message en vult hem automatisch in.
- `python-osc` toegevoegd aan `requirements.txt` (pure Python, geen
  build-tools nodig).
- Per-cue **Fade-in** en **Fade-out** (s) op Audio-cues in de inspector.
  Overlappende audio-cues geven hiermee een natuurlijke crossfade: bij
  AUTO_FOLLOW start de volgende cue zodra de main-playback van de huidige
  cue eindigt, terwijl de fade-out parallel doorloopt. Fields worden
  meegenomen in de workspace-roundtrip.
- Voorkeuren-dialog (Bestand → Voorkeuren…, Ctrl+,) met output-device- en
  samplerate-keuze. Selectie wordt via QSettings persistent opgeslagen op
  basis van device-naam (niet index), zodat USB-herconnects geen invloed
  hebben. Bij opstart laadt liveFire de opgeslagen keuze; onbeschikbare
  devices vallen terug op systeem-default.
- `AudioEngine.set_device()` + `list_output_devices()` + 
  `find_device_index_by_name()` voor veilige engine-herconfiguratie
  (stopt eerst alle actieve cues; rolt terug bij startfout).
- Tests voor de engine-configuratie-API in `tests/test_audio_engine.py`.

### Gewijzigd
- Spinbox-pijltjes (up/down) weer zichtbaar in het dark-theme via
  expliciet gegenereerde arrow-pixmaps; in Qt-stylesheet-mode tekent Qt
  geen native glyph meer. `STYLESHEET` is hierdoor een
  `build_stylesheet()`-functie geworden (moet ná QApplication() draaien).
- Inspector-edits triggeren een targeted refresh van de cuelist-rij in
  plaats van een full clear/rebuild, zodat keyboard-focus op spinboxen
  niet wegspringt tijdens typen.
- Inspector-kleurveld is nu een dropdown met preset cue-kleuren (QLab-stijl)
  inclusief kleur-swatches. Niet-preset hex-waarden uit oudere workspaces
  blijven bewaard als "Aangepast".
- Cue-kleur is in de cuelist nu zichtbaar als gekleurde balk op de
  nummer-kolom plus subtiele row-tint, in plaats van alleen een (nauwelijks
  zichtbare) tekstkleur op het nummer.

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
