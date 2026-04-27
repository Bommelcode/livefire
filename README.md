# liveFire

Cue-based playback voor Windows live events. QLab-geïnspireerd, Windows-native.

**Huidige versie: 0.5.1**

> Tot v0.2.x heette dit project *QCue* — zie CLAUDE.md voor context.

## Features

### Cue-types
- **Audio** — sample-accurate `sounddevice` master-mixer + numpy. Auto-resample
  via `scipy.signal.resample_poly` als de file niet op de engine-samplerate
  (default 48 kHz) staat. Per-cue volume (dB), loops, in/uit-offsets, fade-in
  en fade-out. Overlappende audio-cues geven via AUTO_FOLLOW een natuurlijke
  crossfade.
- **Video** — libVLC + `python-vlc`, fullscreen output op een gekozen scherm.
  Trim (in/uit-punt) met thumbnail-preview en sleepbare tijdlijn-markers,
  per-cue volume (−96..0 dB), fade-in/fade-out, en de optie *Bewaar laatste
  frame na einde*. Tussen video-cues blijft een zwart fullscreen window
  hangen ('lingering'); AUTO_FOLLOW preload't de volgende video voor een
  naadloze cut zonder UI-flits.
- **Afbeelding** *(nieuw in v0.4.1)* — fullscreen still-images via een Qt-only
  engine (geen libVLC). Per output-scherm één 'eigenaar', maar tijdens
  een overgang met `image_fade_in > 0` blijven oude en nieuwe cue kort
  gelijktijdig zichtbaar voor een crossfade (oude fadet uit op het tempo
  van de nieuwe). Bij harde cut (fade_in = 0) sluit de oude direct.
  Per-cue fade-in/fade-out via window-opacity. `duration > 0` →
  auto-fade-out na N seconden; `duration == 0` → image blijft staan tot
  vervanging of een Stop-cue.
- **Presentatie (PowerPoint)** — COM-besturing van een lopende
  PowerPoint-instance. Acties: Open / Volgende slide / Vorige / Goto / Sluit.
  Audio, video, animaties, transities en hyperlinks blijven werken want
  PowerPoint zelf blijft de speler. AUTO_FOLLOW op een Open-cue wacht tot de
  slideshow afloopt en sluit 'm netjes (geen "klik om af te sluiten"-zwarte
  slide). Editor-window wordt geminimaliseerd zodat die nooit over een
  volgende cue verschijnt. Vereist Windows + Microsoft PowerPoint;
  zonder Office degraded gracefully.
- **Network (OSC-out)** *(nieuw in v0.4.1)* — stuurt een OSC-message
  naar een externe ontvanger over UDP. Address, host, port en
  comma-separated args (auto-typed naar int/float/string, met `"..."`-
  quoting). Voor Companion-knoppen, QLab cues, of een direct
  geadresseerde mengtafel/lichttafel. Inspector heeft een
  *Test verzenden*-knop zodat je de connectie kunt valideren zonder
  de cue te draaien.
- **Fade**, **Stop**, **Start** — target-cue gebaseerd.
- **Wait**, **Group**, **Memo**.

### Workspace
- Save/load als `.livefire`-JSON met expliciete `format_version` en migratie
  vanaf v1 (`.qcue`-inhoud).
- Engine-status registry: iedere engine meldt z'n status, zichtbaar via
  `Help → Engine-status` en in de statusbar.

### Triggers (input)
- **OSC-input** — elke cue krijgt een optioneel `trigger_osc` veld
  (bv. `/livefire/go/intro`); inkomende OSC-messages vuren de cue af.
  UDP-poort en enable-flag instelbaar via Voorkeuren (default 53000, uit).
- **"Learn…"-knop** in de inspector vult het OSC-trigger-veld automatisch in
  op basis van de eerstvolgende OSC-message.

### Companion / Stream Deck integratie
liveFire spreekt OSC met [Bitfocus Companion](https://bitfocus.io/companion)
zodat een Stream Deck automatisch met cues + live feedback gevuld kan worden.

**Built-in transport-API** (commands die Companion naar liveFire stuurt):
`/livefire/go`, `/livefire/stop_all`, `/livefire/playhead/{next,prev,goto}`,
`/livefire/fire/<cue_number>`. Werkt naast het bestaande per-cue
`trigger_osc`-veld, dus oude flows breken niet.

**Feedback push** (liveFire → Companion, configureerbaar via Voorkeuren →
Companion): periodiek (default 100 ms) `/livefire/playhead`,
`/livefire/active`, `/livefire/remaining`, `/livefire/remaining/label`,
`/livefire/countdown_active`. On-event per-cue state +
`/livefire/cuecount`. Companion's variables-systeem leest dit direct in
zodat `$(livefire:remaining_formatted)` op een Stream Deck-knop terugtelt.

**Companion-module** als losse repo:
[**Bommelcode/companion-module-livefire**](https://github.com/Bommelcode/companion-module-livefire)
— TypeScript Node.js-project met `@companion-module/base`, kant-en-klare
**presets** voor GO / Stop All / Playhead next/prev / remaining-time tile /
quick-fire 1..16 die oplichten zodra hun cue running is. Build met
`yarn install && yarn build` en wijs Companion's *Settings → Developer
modules* naar de gekloonde map. Volledige OSC-contract-tabel staat in
de README van die repo.

### UI
- Dark theme met cue-list, inspector, transport bar.
- App-icoon zichtbaar in titlebar, Alt-Tab en taskbar (eigen
  AppUserModelID op Windows zodat de taskbar liveFire niet onder
  "Python" groepeert).
- Splashscreen bij opstart (3.5 s); `Help → Over liveFire` toont dezelfde
  pixmap.
- Cue-kleur als gekleurde balk op de nummer-kolom + subtiele row-tint.
  Inspector-kleurveld is een dropdown met preset cue-kleuren (QLab-stijl).
- **Taalkeuze NL / EN** via Voorkeuren (vereist app-restart).
- Keyboard shortcuts: Space = GO, Esc = Stop All, Ctrl+1..9 + Ctrl+0
  = nieuwe cue, Ctrl+↑/↓ = verplaats, Ctrl+, = Voorkeuren.

### Drag-and-drop import
Drop bestanden in de cuelist:
- `.wav` / `.mp3` / `.flac` / `.ogg` / `.aiff` / `.m4a` → Audio-cue
- `.mp4` / `.mov` / `.avi` / `.mkv` / `.webm` → Video-cue
- `.png` / `.jpg` / `.bmp` / `.tif` / `.gif` → Afbeelding-cue *(v0.4.1: was Memo placeholder)*
- `.pptx` / `.pptm` / `.ppt` → **vraagt hoe je 'm wil toevoegen** *(nieuw in v0.4.1)*:
  - **Slides als ingebedde afbeeldingen** (default) — exporteert iedere
    slide via PowerPoint COM naar PNG in
    `<pptx_parent>/<pptx_stem>_slides/slide_NNN.png` en maakt per slide
    een Afbeelding-cue. Daarna heb je geen PowerPoint meer nodig om de
    show te draaien. QProgressDialog met cancel-knop tijdens de export.
  - **Eén Presentatie-cue** — alleen een Open-cue (huidige gedrag);
    PowerPoint blijft de speler en je stuurt slides via aparte
    Volgende/Vorige/Goto-cues of de PowerPoint-clicker.

  Slide-aantal voor `.pptx`/`.pptm` wordt vooraf in de dialog getoond via een
  pure-Python ZIP-XML-telling (geen PowerPoint-launch nodig). Bij meerdere
  PPTs in dezelfde drop verschijnt een *Toepassen op alle*-checkbox. Als
  PowerPoint COM niet beschikbaar is (geen Office of niet-Windows) is de
  slides-optie automatisch uitgeschakeld.

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
pytest                  # 29 tests groen, 1 skip
python -m livefire
```

## Projectstructuur

Zie `CLAUDE.md` voor het volledige architectuuroverzicht en de roadmap.

## Licentie & prijzen

liveFire werkt freemium:

- **Gratis** — Audio + organisatorische cues (Wacht, Stop, Fade, Start,
  Groep, Memo). Een complete audio-only show kun je daarmee bouwen
  zonder licentie.
- **Pro** — Video, Afbeelding, Presentatie en Network (OSC-out). Drie
  termijnen:

  | Termijn  | Prijs    |
  |----------|----------|
  | 1 dag    | € 4,95   |
  | 1 maand  | € 13,95  |
  | 1 jaar   | € 139,95 |
  | Lifetime | € 249,95 |

Je kunt zonder licentie probleemloos workspaces bouwen en bewerken die
Pro-cues bevatten — alleen de uitvoering bij **GO** wordt geblokkeerd
(met een waarschuwing in de statusbar). Zo kun je een show klaarzetten
voor een evenement en pas op de showdag een dag-licentie kopen.

Activeren gaat via *Help → Licentie…* — daar plak je de key die je per
mail hebt ontvangen. Validatie is volledig lokaal (HMAC) — geen server
roundtrip nodig, werkt offline.

## Roadmap

- **v0.4.x** — MIDI in/out (outgoing MIDI-cues + extern timecode),
  echte Group-cues met parent/child tracking en fire-modes,
  audio-matrix per cue (multi-output routing). Companion / Stream Deck
  triggering staat al ✓ — zie *Companion / Stream Deck integratie*.
- **v0.5.0** — DMX/Art-Net + sACN voor licht-cues
- **v0.6.0** — NDI-out, Cart-cue UI (soundboard-grid), MTC/LTC
  in/out (timecode chase + generate)
- **v1.0.0** — Inno Setup `.exe` installer, docs, publieke release

Bewust *niet* op de roadmap (te diep in de stack):

- Video mapping / edge blending / surface masks — libVLC dekt dit
  niet, en een Resolume-achtige render-pipeline valt buiten scope
- Multi-machine network-cues à la QLab (één liveFire die een tweede
  liveFire op een andere PC triggert) — kan grotendeels al via
  OSC-out + OSC-in tussen twee instances
