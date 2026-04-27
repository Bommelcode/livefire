# Changelog

Alle noemenswaardige wijzigingen aan dit project. Format volgens
[Keep a Changelog](https://keepachangelog.com/nl/1.1.0/).

## [Unreleased]

DMX als nieuw cue-type — Art-Net + sACN (E1.31), drie modes (snapshot,
fade, chase), pure-Python output zonder externe dep.

### Toegevoegd
- **DMX-cue** met velden voor protocol (Art-Net / sACN), universe,
  target-host (leeg = broadcast/multicast), port, mode (snapshot / fade
  / chase), values (`1:255, 17:128`), fade_time, chase-steps
  (`1:255 | 1:0,17:255 | 17:0`), step_time, chase_loops (0 = ∞),
  ping-pong-flag.
- **`livefire/engines/dmx.py`** — `DmxEngine` met één 512-byte buffer
  per `(protocol, universe)` en een daemon-thread die alles continu
  pusht op de geconfigureerde refresh-rate (default 30 Hz, range
  5..60 Hz). LTP-merge: latere cue overschrijft eerdere op dezelfde
  channels. Fade interpoleert lineair in de sender-loop; chase
  doorloopt z'n stappen en eindigt na `chase_loops` cycles, of looped
  oneindig bij 0.
- **Pure-Python packet-encoders** voor Art-Net (ArtDMX, OpCode 0x5000)
  en sACN E1.31 — `struct` + raw UDP socket, geen externe dep.
- **Inspector-groep** voor DMX met protocol-aware default-port (6454 ↔
  5568), mode-aware visibility (values+fade vs chase-steps+step-time+
  loops+pingpong).
- **Cue-toolbar-glyph** voor DMX (5-fader-strip), cue-menu-entry
  *New DMX Cue* (Ctrl+Shift+D).
- **Engine-status registry** entry voor DMX met universe-count +
  refresh-rate of laatste error.

### Gewijzigd
- **Stop All** zet alle DMX-universes op nul (blackout) — paniek-knop
  neemt lichten mee.

## [0.4.2] — 2026-04-27

Companion / Stream Deck-integratie, undo/redo + cut/copy/paste,
Engelstalige UI als default, freemium-licensing tijdelijk uit, en
een grondige UX-pass.

### Toegevoegd
- **Companion-integratie (OSC)** — nieuwe `OscFeedbackEngine` pusht
  periodiek (default 100 ms) en on-event de transport-state naar een
  configureerbare host:port. Adressen: `/livefire/playhead`,
  `/livefire/active`, `/livefire/remaining`,
  `/livefire/remaining/label`, `/livefire/countdown_active`, plus
  per-cue `/livefire/cue/<n>/{state,name,type}` en `/livefire/cuecount`.
  Controller-router voor inkomende commands `/livefire/go`,
  `/livefire/stop_all`, `/livefire/playhead/{next,prev,goto}` en
  `/livefire/fire/<cue_number>` — werkt naast het bestaande per-cue
  `trigger_osc`-veld zodat oude flows niet breken. Voorkeuren →
  Companion sectie (host/port/enable/interval).
- **Companion-module** als losse repo
  [Bommelcode/companion-module-livefire](https://github.com/Bommelcode/companion-module-livefire) —
  TypeScript Node.js-project (`@companion-module/base` 1.10) met
  actions, feedbacks, variables, en Stream Deck-presets voor transport,
  status (incl. `$(livefire:remaining_formatted)` countdown-tile) en
  fire-by-number 1..16 die oplichten zodra hun cue running is.
- **Undo / Redo** voor alle workspace-mutaties — Edit-menu met
  Ctrl+Z / Ctrl+Y. Commands voor add/remove/move/renumber + set-field
  met `mergeWith` zodat snel scrollen door een spinbox of typen in een
  textfield als één undo-stap geldt.
- **Cut / Copy / Paste van cues** (Ctrl+X / Ctrl+C / Ctrl+V) — JSON
  serialisatie via clipboard met eigen MIME-type, paste genereert
  nieuwe UUIDs zodat duplicaten hun eigen identity hebben.
- **Inline Continue-dropdown** — klik in de Continue-kolom in de cuelist
  om de mode direct te wijzigen; multi-select propageert de wijziging
  naar alle geselecteerde cues.
- **PPT-import: timing-tree + embedded media** — `extract_slide_media`
  leest het `<p:timing>`-tree per slide en levert per media-item
  trigger (auto/click), delay, loop, volume. De import-flow vertaalt
  dat naar `continue_mode = AUTO_CONTINUE` op de vorige cue,
  `pre_wait`, `loops = 0`, en `volume_db` (geklemd −60..0 dB).
- **Engine-status registry** voor de Companion-feedback-engine.

### Gewijzigd
- **UI-taal**: Engelse strings als default (i18n NL/EN-toggle blijft).
  Alle hardcoded Nederlandse strings in mainwindow / inspector /
  cuelist / cuetoolbar / transport / dialogs zijn vertaald.
- **Freemium licensing tijdelijk uit** via `LICENSING_ENABLED = False`
  — alle cue-types zijn open, code blijft staan voor latere re-enable.
  Help → Licentie-menu wordt verborgen wanneer disabled.
- **Visual Studio-stijl UI** — Segoe UI 9pt globaal, knoppen +
  inputs lager, spinbox up/down naast elkaar (full-height),
  selection-background expliciet zodat Windows-accent niet
  binnen-bleed't.
- **Cue-toolbar** als witte vector-glyphs (4× supersampled QPainter,
  geen asset-files) i.p.v. tekstlabels.
- **Kleurkiezer** is een rij swatches (oranje ring op selectie,
  diagonale streep voor "None") i.p.v. een dropdown.
- **Radio buttons** gestyled met oranje dot voor leesbaarheid op
  donker thema.
- **Cue-shortcuts** hernummerd in menu-volgorde: Ctrl+1 Audio, +2 Video,
  +3 Image, +4 Presentation, +5 Network, +6 Fade, +7 Wait, +8 Stop,
  +9 Group, +0 Memo.
- **Cue-menu**: padding zodat sneltoets-aanduiding niet tegen het
  label aankruipt.
- **Splitter**: cue-list groeit met het venster, inspector pinned aan
  de rechterrand. Cue-toolbar in een horizontale scroll-area zodat
  splitter-drag niet vast zit aan de toolbar-breedte.
- **Window-geometrie persistent** met scherm-overlap-guard: als een
  extern scherm verdwenen is, klapt 't venster terug naar gecentreerd
  i.p.v. buiten beeld te zitten.
- **PPT-import dialog**: option-omschrijvingen gebruiken `TEXT_DIM`
  i.p.v. `palette(mid)` (was onleesbaar op donker thema).

### Opgelost
- **Image-flicker** bij harde cuts tussen image-cues — `ImageWindow`
  opacity wordt expliciet gezet vóór `show_fullscreen()`, en de vorige
  cue wordt pas hard-gesloten ná het tonen van het nieuwe window.
- **OSC-input thread** wordt nu gejoind in `stop()` zodat de UDP-socket
  vrijkomt vóór reuse — geen "address already in use" meer bij
  Preferences-toggle, geen ResourceWarnings in tests.
- **OscLearnDialog** disconnect ook in `closeEvent`, niet alleen via
  accept/reject — voorkomt `RuntimeError` als de modal via X gesloten
  wordt en daarna een OSC-bericht binnenkomt.
- **OscOutputEngine.send()** sluit het socket van een geëvicte client
  zodat snelle sends naar een onbereikbare host geen file-descriptors
  lekken.
- **Diverse test-cleanup-paden** strakker (th.join na server-shutdown,
  expliciete eng.shutdown na sends).

### Documentatie
- **CLAUDE.md** gesynchroniseerd met v0.4.1 — versie, projectstructuur,
  voltooide roadmap-items, huidige tech stack incl. licensing-flag en
  Companion-integratie.
- **README.md** beschrijft de Companion-integratie met OSC-contract en
  linkt naar de losse module-repo.

## [0.4.1] — 2026-04-26

Image-cue als nieuw cue-type, plus PPT-import-keuze: laat de show
draaien op ingebedde slide-PNGs (geen PowerPoint nodig tijdens de show)
of gebruik PowerPoint als speler.

### Toegevoegd
- **Image-cue** — fullscreen still-images via een nieuwe Qt-only
  `ImageEngine` (geen libVLC nodig). Eén actieve image per output-scherm;
  een tweede image-cue op hetzelfde scherm vervangt de eerste hard.
  Velden: `file_path`, `image_output_screen`, `image_fade_in`,
  `image_fade_out`. Cue-`duration > 0` zorgt voor auto-fade-out na N
  seconden; `duration == 0` laat de image staan tot vervanging of een
  Stop-cue. Inspector heeft nu een Afbeelding-groep.
- **Drag-drop van .png/.jpg/.webp/etc.** maakt nu een echte Image-cue
  (was Memo placeholder).
- **PPT-import-dialog bij drag-drop van .pptx/.pptm/.ppt.** Twee opties:
  *Slides als ingebedde afbeeldingen* (default) exporteert iedere slide
  via PowerPoint COM naar PNG in
  `<pptx_parent>/<pptx_stem>_slides/slide_NNN.png` en plaatst per slide
  een Image-cue — de show draait daarna zonder PowerPoint;
  *Eén Presentatie-cue* (oude gedrag) plaatst alleen een Open-cue.
  Slide-aantal voor `.pptx`/`.pptm` wordt vooraf in de dialog getoond
  via een pure-Python ZIP-XML-telling (geen PowerPoint-launch nodig).
  Bij meerdere PPTs in dezelfde drop verschijnt een
  *Toepassen op alle*-checkbox.
- **Slide-export via COM** — nieuwe `export_slides_to_png(file_path,
  output_dir, width, height, progress_callback)`-helper. Opent de
  presentatie read-only zonder window, minimaliseert eventuele
  editor-windows en exporteert per `Slide.Export(..., "PNG", w, h)`.
  Default 1920×1080. Cancel-support via callback (return `True`).
- **QProgressDialog** tijdens de export, modal, met cancel-knop en per-
  slide voortgang.
- i18n-keys: `cuetype.Image`, `group.image`, alle `pptimport.*`-strings
  in NL en EN.
- **Crossfade tussen image-cues op hetzelfde scherm.** Wanneer een
  nieuwe image-cue met `image_fade_in > 0` start op een scherm waar al
  een cue draait, krijgt de oude een fade-out van dezelfde duur en
  zijn beide windows kort gelijktijdig zichtbaar (nieuwere bovenop).
  Een vorige cue die zelf al een fade-out had ingezet (Stop-cue,
  duration verlopen) loopt op z'n eigen tempo uit. Bij `image_fade_in
  == 0` blijft de oude harde-cut-vervang gedrag actief zodat onnodige
  pixmaps niet in geheugen blijven hangen.
- **Network-cue** voor OSC-out. Nieuw cue-type dat een OSC-message
  stuurt naar een externe ontvanger (Companion, QLab, mengtafel,
  lichttafel). Velden: `network_address` (bv.
  `/companion/page/1/button/1`), `network_args` (comma-separated tekst
  met auto-typing int → float → string en `"..."`-quoting),
  `network_host` (default `127.0.0.1`), `network_port` (default 53000).
  Verzenden gebeurt synchroon vanuit `_begin_action` (UDP, geen retry).
  Inspector heeft een **"Test verzenden"-knop** zodat je tijdens het
  bouwen van een show de connectie kunt valideren zonder een GO te
  doen. Nieuwe `OscOutputEngine` (in `engines/osc_out.py`) hergebruikt
  de bestaande `python-osc` dependency. Menu-item *Cue → Nieuwe
  Network-cue*.
- **Menu-item Nieuwe Afbeelding-cue (Ctrl+0)** — voorheen alleen
  bereikbaar via drag-drop of door een bestaand cue-type via de
  inspector om te zetten naar Image.

### Gewijzigd
- `CueType.ALL` bevat nu `IMAGE` (tussen `VIDEO` en `PRESENTATION`).
- Workspace-format blijft v2; nieuwe image-velden krijgen defaults
  bij oude workspaces zonder migratie.

### Bekend
- Slide-export vereist Microsoft PowerPoint op Windows. Zonder
  COM is de slides-optie in de import-dialog automatisch uitgeschakeld
  en valt de keuze terug op één Presentatie-cue.
- Goto-cues per slide (PowerPoint blijft de speler) zijn niet als optie
  opgenomen — die rol vervult nu de single Presentatie-cue plus
  handmatige Volgende/Vorige-cues vanuit de inspector.

### Verholpen (debug-pass)
- ImageWindow heeft `WA_DeleteOnClose=False` (was `True`) om te
  voorkomen dat een lopende `QPropertyAnimation` op een net gedelete
  Qt-object schiet bij teardown.
- ImageWindow start expliciet op `windowOpacity=0` in `__init__` zodat
  fade-in geen 100%-flash geeft op Windows tussen `show()` en de eerste
  animation-frame.
- `QPropertyAnimation` voor image fade-in/-out heeft nu het window
  zelf als parent (was de engine), zodat anim met window mee opruimt.
- `_hard_close` en `_finalize_close` doen nu expliciet `deleteLater()`
  na `close()`.
- `export_slides_to_png` schaalt slide-resolutie aspect-correct via
  `Presentation.PageSetup.SlideWidth/SlideHeight` in plaats van een
  vaste 1920×1080 (die 4:3 presentaties zou stretchen). Default
  `max_dim=1920` voor de langste zijde.
- `ImageEngine.is_playing()` komt nu overeen met `VideoEngine.is_playing()`-
  contract: `True` zolang de engine de cue beheert (inclusief tijdens
  fade-out), `False` pas zodra de entry uit `_active` is verwijderd.
  Daarmee start `post_wait` in de controller pas ná de visuele fade-out
  in plaats van ertijdens (eerder dan de bedoeling).
- ImageWindow `_rescale` is nu high-DPI-aware: schaalt naar `size() ×
  devicePixelRatio` en zet de DPR op de output-pixmap. Op een 4K
  projector met 200% scaling levert dit een scherp beeld in plaats van
  een uitgerekte 1080p-versie.
- `Presentation.Saved = True` voor `Close()` zodat PowerPoint nooit een
  save-prompt opent na slide-export, zelfs als het z'n eigen 'modified'-
  flag zet.
- Dood `from ..cues import PresentationAction` boven aan
  `_on_files_dropped` opgeruimd.
- Inspector verbergt bij deselect (`set_cues([])`) ook `grp_image` en
  `grp_network` — voorheen bleven die met stale data zichtbaar van de
  vorige cue.
- `export_slides_to_png` vangt `OSError` bij `mkdir` op (bv. geen
  schrijfrechten op de pptx-parent) en retourneert een nette
  foutmelding in plaats van te crashen.
- `OscOutputEngine` cache't `SimpleUDPClient` per `(host, port)` zodat
  Network-cue chains niet voor iedere cue een nieuwe socket openen
  (ephemeral-port range bescherming + minder TIME_WAIT-resten).
  `shutdown()` sluit alle gecachede sockets; corrupte clients worden
  geëvict op send-fout.
- `parse_args` op OSC-args houdt gequote tokens *altijd* string,
  ongeacht inhoud — `"42"` is string `"42"`, niet int `42`. Quoted
  whitespace blijft bewaard (`" "` → `" "`); ongequote tokens worden
  gestript en lege ongequote tokens (consecutive comma's, trailing
  comma) overgeslagen.
- Test-knop op Network-cue gebruikt nu `i18n` (`btn.test_send` /
  `btn.test_send.done`) — vertaalt mee met taalwissel.
- `PlaybackController` heeft een `network_send_failed(cue_id, error)`
  signal dat fire't wanneer een Network-cue's OSC-send mislukt
  (lege/ongeldige address, python-osc niet beschikbaar). De show
  blokkeert niet — de cue gaat door naar post_wait — maar de UI
  heeft nu een hook om het te tonen.
- `stop_all` (Esc / Stop All) sluit nu ook een actieve PowerPoint-
  slideshow. Voorheen bleef die fullscreen over de cuelist hangen
  tot een Close-cue.

### Toegevoegd
- **Freemium licensing.** Audio + organisatorische cues (Wacht, Stop,
  Fade, Start, Groep, Memo) zijn altijd gratis. Video, Afbeelding,
  Presentatie en Network vereisen een Pro-licentie. Vier termijnen:
  dag (€ 4,95), maand (€ 13,95), jaar (€ 139,95), lifetime (€ 249,95).
  Bouwen mag altijd — alleen GO op een Pro-cue zonder licentie wordt
  geblokkeerd, met een waarschuwing in de statusbar.
- **`livefire/licensing.py`** — module-level API met `init()`,
  `current_tier()`, `is_pro()`, `has_feature(cue_type)`,
  `activate(key)`, `deactivate()`, plus een `signaler.license_changed`
  Qt-signal voor UI-componenten. Constants: `PAID_CUE_TYPES`,
  `PRICES_EUR`, `PURCHASE_URL`. Key-format
  ``LF-<TIER>-<YYYY-MM-DD>-<HMAC8>`` met HMAC-SHA256 over
  ``"<TIER>|<expires>"`` — volledig lokaal te valideren, geen server
  roundtrip nodig. Sil's eigen tooling roept `generate_key(tier,
  expires)` aan om keys uit te delen aan klanten; verlopen keys
  verliezen automatisch hun rechten.
- **Help → Licentie…**-dialog — toont status, drie koop-knoppen die
  de browser openen op `<PURCHASE_URL>?tier=...`, een veld om een key
  te plakken + Activeer-knop, en een Verwijder-knop voor wie de
  licentie wil intrekken.
- **`PlaybackController.cue_blocked_by_license`** signal — emit'ed
  wanneer `_begin_action` een paid cue tegenkomt zonder Pro. De cue
  wordt overgeslagen, AUTO_CONTINUE chain't door zodat de show niet
  vastloopt, en MainWindow flash't 6 sec lang een melding in de
  statusbar.
- **Inspector Pro-banner** — zichtbaar als de geselecteerde cue een
  Pro-type is en je hebt geen actieve licentie. Verbergt zich
  automatisch zodra je een licentie activeert (via
  `licensing.signaler.license_changed`).
- `parse_args` (OSC-out token-parsing) gefixt:
  (a) gequote whitespace-strings (`" "`) gingen verloren aan
  ``.strip()``-en-skip-on-empty;
  (b) gequote numerieke strings (`"42"`) werden naar int gecoerced —
  een gequote token moet altijd string blijven (OSC-conventie);
  (c) gemixt-quoted tokens (`1, "hello"`) hadden de leading whitespace
  als deel van de string. Nieuw: per-karakter quote-tracking, alleen
  *unquoted* whitespace aan begin/eind wordt gestript.
- `PlaybackController.stop_all()` sluit nu ook een actieve PowerPoint-
  slideshow. Esc / Stop All zou anders het PowerPoint-window over de
  cuelist laten staan tot een Close-cue. Bestaand bug — niet
  geïntroduceerd in v0.4.1, maar wel opgelost.
- Network-cue OSC-send-fouten worden gesignaleerd via een nieuwe
  `network_send_failed(cue_id, error_message)`-signal op de
  `PlaybackController`. MainWindow connect en toont 4s een
  ⚠-melding in de statusbar zodat de operator weet dat een trigger
  niet aankwam (UDP heeft geen native ack — ander zou het 'silent'
  zijn).
- Lazy import van `parse_args` in de controller's tick-loop verplaatst
  naar module-top (cosmetisch).

## [0.4.0] — 2026-04-25

Grote feature-release. Bevat alles wat de oorspronkelijke roadmap voor
v0.3.x t/m v0.6.0 in stapjes had ingedeeld plus extra features die uit
de praktijk zijn voortgekomen.

### Toegevoegd
- **Naadloze video-overgangen.** Tussen video-cues blijft een fullscreen
  window staan met zwarte achtergrond ('lingering'), zodat we tussen
  manual GO's nooit terug naar de UI flitsen. Per-cue checkbox
  *Bewaar laatste frame na einde* houdt de video paused op het laatste
  frame in plaats van zwart. AUTO_FOLLOW preload't de volgende video
  tijdens de huidige cue (verborgen window + gedecodeerd eerste frame)
  voor een naadloze cut. Manual GO na een lingering frame: nieuwe
  window blijft 220 ms transparant achter de paused frame zodat libVLC
  kan decoderen, daarna in één klap zichtbaar met 60 ms cleanup-overlap.
- **Taalkeuze NL / EN.** Nieuwe `livefire/i18n.py` met `t(key)`-lookup
  en NL+EN-dictionaries; cuelist-kolommen, cue-types, cue-states,
  continue-modes en inspector groep-titels worden vertaald getoond.
  Workspaces blijven compatibel — `Audio` / `Video` / etc. blijven de
  interne values. Voorkeuren krijgt een Interface-groep met de
  taal-keuze; wijziging vereist app-restart.
- **Presentatie-cue** (PowerPoint via COM). Nieuw cue-type met acties
  Open / Volgende slide / Vorige slide / Ga naar slide / Sluit. Audio,
  video, animaties, transities en hyperlinks blijven werken want
  PowerPoint blijft de speler — liveFire is alleen de cue-trigger.
  AUTO_FOLLOW op een Open-cue wacht tot de slideshow klaar is, sluit
  de presentatie automatisch (geen "klik om af te sluiten"-zwarte
  slide), en minimaliseert de PowerPoint-editor zodat die nooit over
  een volgende cue blijft staan. Drag-and-drop van .pptx/.ppt/.pptm,
  Ctrl+9 voor nieuwe cue, eigen knop in de toolbar. Vereist
  Microsoft PowerPoint en `pywin32` op de showmachine; engine
  registreert zich in Engine-status, degraded gracefully zonder.

### Toegevoegd
- **App-icoon** (`livefire/resources/icon.png`) zichtbaar in titlebar,
  Alt-Tab en taskbar. Op Windows wordt een AppUserModelID gezet zodat
  de taskbar liveFire niet onder "Python" groepeert.
- **Splashscreen** bij opstart (3.5 s) met icoon, appnaam, versienummer
  en ondertitel — verschijnt over de hoofd-UI. Help → Over liveFire
  toont dezelfde pixmap in een dialog met sluit-knop.

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
