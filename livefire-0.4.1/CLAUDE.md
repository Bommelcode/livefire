# liveFire

QLab-geïnspireerde cue-based playback applicatie voor Windows live events.
Eigenaar: Sil Stranders (S.I.L. Stranders, AV freelance, NL).

> **Geschiedenis:** tot en met v0.2.x heette deze app **QCue** (single-file
> `qcue.py`). Bij de v0.3.0 refactor naar modulaire package + sounddevice-
> engine is de app hernoemd naar **liveFire**. Package-naam is `livefire`,
> workspace-extensie is `.livefire`.

## Doel

Cue-based audio / video / MIDI / OSC / DMX playback voor live shows. Moet
draaiend te krijgen zijn op showlocaties zonder internet. Wordt mogelijk gedeeld
met AV-collega's — eindtoestand is een Windows `.exe` installer.

Huidige versie: **0.3.0** (modulaire package, sounddevice master-mixer audio
engine, skeleton met Audio/Fade/Wait/Stop/Start/Group/Memo cues).

## Tech stack

- **Taal**: Python 3.11+ (Windows native, geen WSL)
- **GUI**: PyQt6
- **Audio**: `sounddevice` + `numpy` + `soundfile` (master-mixer in numpy,
  WASAPI shared/exclusive op Windows, optioneel ASIO). Per-cue streams mixen
  we softwarematig zodat matrix + crossfades mogelijk worden in v0.3.x.
- **Video** (gepland v0.6.0): `python-vlc` als eerste keus vanwege hw-accel
  en codec-dekking; `cyndilib` voor NDI-out. Fallback PyAV+OpenGL als libVLC
  tegenvalt.
- **MIDI** (gepland v0.4.0): `mido` + `python-rtmidi` (in + out)
- **OSC** (gepland v0.4.0): `python-osc` (in + out)
- **DMX** (gepland v0.5.0): `pyartnet` (Art-Net), `sacn` (sACN E1.31)
- **Packaging** (gepland v1.0.0): PyInstaller + Inno Setup
- **Tests**: `pytest` handmatig; geen CI-verplichting (nog)

## Projectstructuur (huidige v0.3.0)

```
livefire-0.3.0/
├── livefire/
│   ├── __init__.py           # versie, constanten, WORKSPACE_EXT
│   ├── __main__.py           # python -m livefire
│   ├── workspace.py          # .livefire save/load + versiemigratie
│   ├── cues/
│   │   ├── __init__.py
│   │   └── base.py           # Cue dataclass, CueType, ContinueMode
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── audio.py          # sounddevice master-mixer + AudioSource
│   │   └── registry.py       # engine-status registry
│   ├── playback/
│   │   ├── __init__.py
│   │   └── controller.py     # GO-pipeline, pre/post-wait, continues
│   └── ui/
│       ├── __init__.py
│       ├── mainwindow.py
│       ├── cuelist.py
│       ├── inspector.py
│       ├── transport.py
│       ├── style.py          # dark theme stylesheet
│       └── dialogs/
│           ├── about.py
│           └── engine_status.py
├── tests/
│   └── test_workspace.py
├── installer/                # leeg — Inno Setup komt in v1.0
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── CLAUDE.md
├── README.md
└── CHANGELOG.md
```

Geplande uitbreiding van deze structuur per release:
- v0.4.0 → `livefire/cues/midi.py`, `livefire/cues/osc.py`, `engines/midi.py`, `engines/osc.py`
- v0.5.0 → `livefire/cues/dmx.py`, `engines/dmx.py`
- v0.6.0 → `livefire/cues/video.py`, `engines/video.py`
- v1.0.0 → `installer/livefire.iss` + `livefire.spec`

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

1. **v0.3.0** (huidig) — Refactor single-file → modules + audio-engine
   migratie naar sounddevice master-mixer. Audio/Fade/Wait/Stop/Start/
   Group/Memo cue-types werkend.
2. **v0.3.1** — Output-device picker (QSettings), per-cue output-device,
   audio-matrix routing.
3. **v0.3.2** — Crossfades tussen overlappende audio-cues.
4. **v0.4.0** — OSC-in + MIDI-in (cue-triggering vanaf Companion / Stream
   Deck / externe consoles). Inclusief "learn" dialog in de inspector.
5. **v0.5.0** — DMX/Art-Net + sACN cue-types met preset + chase + fade.
6. **v0.6.0** — Video-engine: libVLC voor hw-accel, cyndilib voor NDI-out,
   multi-screen output, fade-to-black.
7. **v1.0.0** — Installer (.exe via PyInstaller + Inno Setup), docs,
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
