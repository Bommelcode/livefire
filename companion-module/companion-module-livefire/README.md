# companion-module-livefire

[Bitfocus Companion](https://bitfocus.io/companion) module for **liveFire** — drives liveFire's transport, playhead, and per-cue triggers from a Stream Deck, with live feedback (running cues, remaining time, playhead position).

## What it gives you

**Actions** (button bindings)
- `GO` — fire the cue at the playhead and advance
- `Stop All` — panic-stop all running cues
- `Playhead: next / previous / go to index`
- `Fire cue by number` — match against the cuelist's `Nr` column

**Feedbacks** (visual button state)
- *Cue is in state* — light up when a specific cue is running/finished/idle
- *Countdown active* — orange glow while a finite-duration cue counts down
- *Any cue running* — blue when at least one cue is playing
- *Playhead at index* — light the button matching the current playhead

**Variables** (text values)
- `$(livefire:remaining_formatted)` — `m:ss` for short cues, `s.s` under 60 s, prefixed with `+` for count-up infinite loops
- `$(livefire:remaining)` — raw seconds (negative = count-up)
- `$(livefire:remaining_label)` — name of the cue driving the countdown
- `$(livefire:playhead)`, `$(livefire:playhead_total)`, `$(livefire:playhead_name)`
- `$(livefire:active)` — how many cues are running
- `$(livefire:cuecount)` — total in workspace

**Presets** (drag-and-drop button layouts)
- *Transport*: GO, Stop All, Next, Prev
- *Status*: Remaining-time tile, Active-count tile, Playhead-label tile
- *Fire by number*: 16 quick-fire tiles for cues numbered `1`..`16`, each lighting up green when their cue is running

## Setup

1. **In liveFire** → `Preferences…` → `OSC input`: enable, pick a UDP port (default 53000).
2. **In liveFire** → `Preferences…` → `Companion`: enable "Push feedback to Companion", set host to the machine running Companion (`127.0.0.1` if same box), and pick a feedback port (default 12321).
3. **In Companion** → add a connection → `liveFire`. Set:
   - *liveFire host* — same address as where liveFire runs
   - *OSC-input port* — match liveFire's OSC-input UDP port (53000)
   - *Feedback port* — match liveFire's Companion → Port (12321)
4. Drag presets from the *Presets* panel onto your Stream Deck.

## Develop

```bash
yarn install
yarn build
# or live-rebuild while editing:
yarn watch
```

For local testing in Companion: in Companion's Settings → "Developer modules", point at this folder. Companion will reload on rebuild.

To package for distribution:
```bash
yarn package
```
…then either install the resulting `.tgz` via Companion's "Manual module install" or open a PR against [bitfocus/companion-module-requests](https://github.com/bitfocus/companion-module-requests).

## OSC contract

This module is purely a UI for the OSC API liveFire exposes. Spec is in [`livefire/engines/osc_feedback.py`](../../livefire/engines/osc_feedback.py) (push) and [`livefire/playback/controller.py:_handle_livefire_command`](../../livefire/playback/controller.py) (commands).

| Direction | Address | Args |
|---|---|---|
| → liveFire | `/livefire/go` | — |
| → liveFire | `/livefire/stop_all` | — |
| → liveFire | `/livefire/playhead/next` | — |
| → liveFire | `/livefire/playhead/prev` | — |
| → liveFire | `/livefire/playhead/goto` | `int index` |
| → liveFire | `/livefire/fire/<cue_number>` | — |
| ← liveFire | `/livefire/playhead` | `int index, int total, string name` |
| ← liveFire | `/livefire/active` | `int count` |
| ← liveFire | `/livefire/remaining` | `float seconds (signed)` |
| ← liveFire | `/livefire/remaining/label` | `string` |
| ← liveFire | `/livefire/countdown_active` | `int 0/1` |
| ← liveFire | `/livefire/cuecount` | `int` |
| ← liveFire | `/livefire/cue/<n>/state` | `string idle/running/finished` |
| ← liveFire | `/livefire/cue/<n>/name` | `string` |
| ← liveFire | `/livefire/cue/<n>/type` | `string` |

## License

MIT
