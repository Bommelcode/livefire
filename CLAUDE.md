# liveFire

QLab-geïnspireerde cue-based playback applicatie voor Windows live events.
Eigenaar: Sil Stranders (S.I.L. Stranders, AV freelance, NL).

> **Geschiedenis:** tot en met v0.2.x heette deze app **QCue** (single-file
> `qcue.py`). Bij de v0.3.0 refactor naar modulaire package + sounddevice-
> engine is de app hernoemd naar **liveFire**. Package-naam is `livefire`,
> workspace-extensie is `.livefire`.

## Doel

Cue-based audio / video / image / OSC / PowerPoint playback voor live shows.
Moet draaiend te krijgen zijn op showlocaties zonder internet. Wordt mogelijk
gedeeld met AV-collega's — eindtoestand is een Windows `.exe` installer.

Huidige versie: **0.5.1** (Audio + Video + Image + Network/OSC-out +
DMX/Art-Net+sACN + PowerPoint-import incl. timing-tree, OSC-in triggers,
freemium-licensing-systeem aanwezig maar tijdelijk uitgezet via
`LICENSING_ENABLED=False`, Companion / Stream Deck-integratie via een
aparte module-repo, undo/redo + cut/copy/paste voor cues, en echte
group-cues met 4 fire-modes en parent/child nesting).

## Tech stack

- **Taal**: Python 3.11+ (Windows native, geen WSL)
- **GUI**: PyQt6
- **Audio**: `sounddevice` + `numpy` + `soundfile` (master-mixer in numpy,
  WASAPI shared/exclusive op Windows, optioneel ASIO).
- **Video**: `python-vlc` (libVLC) — hw-accel, codec-dekking.
  Multi-screen output, fade-to-black, in/out-trim met preview.
- **Image**: pure Qt (`QPixmap` + frameless `QWidget`) — fullscreen stills
  met fade-in/out + crossfade per output-screen.
- **OSC**: `python-osc` voor input (cue-triggers vanaf Companion / Stream
  Deck) en output (Network-cues).
- **PowerPoint**: COM-besturing via `pywin32` voor live-slideshow + slide-
  export naar PNG. Pure-Python `zipfile`+`xml.etree` parser leest het
  `.pptx`-archief voor slide-count, embedded media, en het timing-tree
  (autoplay/click/loop/volume) zonder PowerPoint te starten.
- **MIDI** (gepland, nog niet aanwezig): `mido` + `python-rtmidi` (in + out).
- **DMX**: pure-Python Art-Net + sACN (E1.31). Geen externe dep — we
  encoderen de packets zelf met `struct` + raw UDP socket. DmxEngine
  houdt per universe een 512-byte buffer aan en pusht 'm continu op
  ~30 Hz; cues schrijven via LTP-merge.
- **Licensing**: lokale HMAC-SHA256 keys (`livefire/licensing.py`). Module
  is volledig geïmplementeerd maar door `LICENSING_ENABLED = False` staan
  alle Pro-features open en is het Help → Licentie…-menu verborgen.
- **Packaging** (gepland v1.0.0): PyInstaller + Inno Setup.
- **Tests**: `pytest` (~100 tests), geen CI-verplichting (nog).

## Projectstructuur (v0.5.1)

```
livefire/
├── livefire/
│   ├── __init__.py           # APP_VERSION, SETTINGS_*, WORKSPACE_EXT
│   ├── __main__.py           # python -m livefire
│   ├── workspace.py          # .livefire save/load + versiemigratie
│   ├── i18n.py               # NL/EN-toggle (via QSettings)
│   ├── licensing.py          # HMAC-keys + LICENSING_ENABLED-flag
│   ├── cues/
│   │   ├── __init__.py
│   │   └── base.py           # Cue dataclass, CueType, ContinueMode,
│   │                         # PresentationAction
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── registry.py       # engine-status registry (Help → Engine-status)
│   │   ├── audio.py          # sounddevice master-mixer + AudioSource
│   │   ├── video.py          # libVLC + preload + lingering windows
│   │   ├── image.py          # Qt fullscreen-still + crossfade
│   │   ├── osc.py            # OSC-input via BlockingOSCUDPServer
│   │   ├── osc_out.py        # OSC-output (Network-cues)
│   │   └── powerpoint.py     # COM-engine + .pptx parser
│   │                         #   (count_slides, extract_slide_media,
│   │                         #    SlideMedia, export_slides_to_png)
│   ├── playback/
│   │   ├── __init__.py
│   │   └── controller.py     # GO-pipeline, pre/post-wait, continues,
│   │                         # license-gate, _tick polling
│   └── ui/
│       ├── __init__.py
│       ├── mainwindow.py     # geometry-persistence, splitter-setup,
│       │                     # PPT-import-flow, drag-drop
│       ├── cuelist.py
│       ├── cuetoolbar.py
│       ├── inspector.py      # ~960 regels, per cue-type een form-groep
│       ├── transport.py
│       ├── video_preview.py  # in/out-trim met scrub-preview
│       ├── style.py          # dark theme stylesheet
│       └── dialogs/
│           ├── about.py
│           ├── engine_status.py
│           ├── license.py
│           ├── ppt_import.py     # slides-export vs single-presentation
│           ├── preferences.py    # device-pickers + OSC-port
│           └── trigger_learn.py  # OSC-learn modal
├── tests/
│   ├── conftest.py
│   ├── test_audio_engine.py
│   ├── test_image_cue.py
│   ├── test_licensing.py
│   ├── test_network_cue.py
│   ├── test_osc.py
│   ├── test_pptx_count.py
│   ├── test_pptx_media.py
│   └── test_workspace.py
├── tools/                    # genkey.py, issue_license.py
├── installer/                # leeg — Inno Setup komt in v1.0
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── CLAUDE.md
├── README.md
└── CHANGELOG.md
```

## Conventies

- **Taal**: UI-labels, statusbalkteksten, foutmeldingen en dialoogteksten in het
  **Nederlands**. Code-identifiers in het Engels.
- **Comments & docstrings**: Nederlands (consistent met bestaande v0.2.x code).
- **Type hints**: verplicht op alle publieke functies en dataclasses.
- **Dark theme**: consistent met huidige liveFire styling; geen lichte modus.
- **Workspace-format**: geen breaking changes in `.livefire` JSON zonder
  migratiepad in `workspace.py`. Altijd een `format_version` veld schrijven.
- **Engine-status**: elke nieuwe engine registreert zich in het Engine-status
  panel (Help → Engine-status) met naam + beschikbaarheid + foutmelding.

## Niet doen

- Geen cloud-afhankelijkheden, geen telemetrie, geen auto-update in de app
  zelf (breekt tijdens show). Updates alleen via nieuwe installer.
- Geen `async/await` architectuur — Qt signals + `QThread` / `QTimer`
  volstaan en zijn consistent met bestaande code.
- Geen nieuwe dependency toevoegen zonder het in `requirements.txt` te zetten
  én in Engine-status zichtbaar te maken als die dependency optioneel is.
- Geen `sudo`/admin-rechten vereisen voor normaal gebruik.
- Geen hardcoded paden; alles via `QSettings` of workspace-relatief.

## Roadmap

Gedaan (v0.3.0 t/m v0.5.1):
- v0.3.0 — Refactor single-file → modules, sounddevice master-mixer.
- v0.3.1/v0.3.2 — Output-device picker (QSettings), crossfades.
- v0.4.0 — OSC-in (Companion/StreamDeck triggers) incl. learn-dialog,
  PowerPoint-cues via COM, video-engine (libVLC), zwart-vrije transitions,
  NL/EN i18n-toggle, app-icoon + splash + Over-dialog.
- v0.4.1 — Image-cues, Network-cues (OSC-out), PowerPoint slide-export
  naar PNGs incl. embedded media (audio/video) en timing-tree-mapping
  (autoplay/click → continue_mode, loop, volume), freemium-licensing
  (HMAC-keys, momenteel uitgezet via `LICENSING_ENABLED`).
- v0.4.2 — Companion / Stream Deck-integratie (OSC feedback engine +
  extended commands + losse module-repo
  [Bommelcode/companion-module-livefire](https://github.com/Bommelcode/companion-module-livefire)),
  undo/redo + cut/copy/paste voor cues, Engelstalige UI als default,
  freemium-licensing tijdelijk uit, en een grondige UX-pass
  (Visual Studio-stijl font, witte vector-glyphs op de cue-toolbar,
  swatch-rij i.p.v. dropdown voor kleuren, inline Continue-dropdown,
  oranje radio-button-dots, sticky inspector aan de rechterrand).
- v0.5.0 — DMX als nieuw cue-type via Art-Net + sACN (E1.31). Pure-
  Python output zonder externe dep, drie modes (snapshot, fade,
  chase). Stop-All blackt uit. 21 nieuwe tests.
- v0.5.1 — Echte group-cues met parent/child-tracking en vier
  fire-modes (list / first-then-list / parallel / random), recursive
  stop-cascade, cuelist als boom met disclosure-arrows + right-click
  context-menu voor "Move into group" / "Move out of group".

Nog te doen:
1. **v0.5.x** — MIDI-in/out (`mido` + `python-rtmidi`), audio-matrix
   per cue (multi-output routing).
2. **v0.6.0** — NDI-out, Cart-cue UI, MTC/LTC timecode in/out.
3. **v1.0.0** — Installer (.exe via PyInstaller + Inno Setup), docs,
   stabilisatieronde, eerste publieke release naar collega's.

## Build / run

```powershell
# Eerste setup
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Ontwikkelen
python -m livefire

# Tests
pytest

# Release-build (vanaf v1.0)
pyinstaller livefire.spec
iscc installer\livefire.iss
```

## Git-workflow

- `main` draait altijd op een show — nooit direct committen.
- Feature branches: `feature/<korte-naam>`, bijv. `feature/audio-sounddevice`.
- Elke feature via PR naar `main`, squash-merge.
- Tag elke release: `git tag v0.3.0 && git push --tags`.
- Elke merge naar `main` update `CHANGELOG.md` (Keep a Changelog-format).

## Werkafspraken met Claude Code

- Begin elke feature met een `feature/...` branch, niet op `main` werken.
- Bij grote wijzigingen eerst een plan voorleggen vóór code schrijven.
- Workspace-format wijzigingen altijd met migratiefunctie in `workspace.py`
  en bumped `format_version`.
- Elke commit bouwbaar (`python -m livefire` start zonder traceback), ook als
  een feature nog niet af is — gebruik feature flags als dat nodig is.
- Houd `CHANGELOG.md` up to date bij elke merge naar `main`.
