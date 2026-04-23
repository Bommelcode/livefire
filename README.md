# liveFire

Cue-based playback voor Windows live events. QLab-geïnspireerd, Windows-native.

**Huidige versie: 0.3.0** (skeleton — zie CHANGELOG)

> Tot v0.2.x heette dit project *QCue* — zie CLAUDE.md voor context.

## Features (v0.3.0)

- Cue-types: Audio, Fade, Wait, Stop, Start, Group, Memo
- Sample-accurate audio via `sounddevice` master-mixer + numpy
- Automatische sample-rate conversion (scipy) bij afwijkende bestanden
- Sample-accurate gain-ramps voor Fade-cues
- Pre-wait / action / post-wait, continue-modes (Do Not Continue, Auto-Continue, Auto-Follow)
- Workspace save/load als `.livefire` JSON met format-versie en migratiepad (leest ook oude `.qcue`-inhoud via de migratie)
- Dark-theme UI met cue-list, inspector, transport bar
- Keyboard shortcuts: Space = GO, Esc = Stop All, Ctrl+1..7 = nieuwe cue, Ctrl+↑/↓ = verplaats

## Starten (Windows)

**Snelste manier — dubbelklik `start.bat`.** Maakt bij eerste run een venv,
installeert dependencies, en start de app. Daarna dubbelklik = start.

Werkt er iets niet? Gebruik `start-debug.bat` — zelfde, maar venster blijft
open met tracebacks.

**Handmatig:**

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m livefire
```

## Een losse livefire.exe bouwen

Voor distributie naar collega's zonder Python-installatie:

```powershell
.\build-exe.ps1
```

Resultaat: `dist\livefire\livefire.exe` (+ dependencies). De hele
`dist\livefire\`-map is portable — kopieer 'm naar elke Windows PC.

Dit is een dev-build. De *echte* installer (met shortcuts, uninstaller,
auto-update-suppressie) komt in v1.0 via Inno Setup.

## Ontwikkelen

```powershell
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                  # 6 tests groen
python -m livefire
```

## Projectstructuur

Zie `CLAUDE.md` voor het volledige architectuuroverzicht en de roadmap.

## Roadmap

- **v0.3.x** — Multi-output routing, audio-matrix, crossfades
- **v0.4.0** — OSC-in + MIDI-in (triggeren vanaf Companion/Stream Deck)
- **v0.5.0** — DMX/Art-Net + sACN
- **v0.6.0** — Video via libVLC + NDI-out
- **v1.0.0** — Inno Setup `.exe` installer, docs, publieke release
