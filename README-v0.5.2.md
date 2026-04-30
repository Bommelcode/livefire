# liveFire v0.5.2 — Stability Layer

Pak deze zip uit **bovenop** je `livefire`-checkout (de map waar
`livefire\__init__.py` al in staat). De paden zijn relatief, dus de
files landen op de juiste plek.

## In PowerShell

```powershell
cd C:\livefire-0.4.1     # of waar je checkout ook staat
# pak de zip uit, accepteer overschrijven
Expand-Archive -Path $HOME\Downloads\livefire-v0.5.2-stability-layer.zip `
               -DestinationPath . -Force

# verifieer dat het werkt
.\.venv\Scripts\activate
pytest                    # moet 164 passed, 1 skipped tonen
python -m livefire        # smoke-test

# committen + pushen
git add -A
git status                # check dat alleen verwachte files in de stage staan
git commit -m "v0.5.2: stability layer — crash-handler, autosave, showtime-lock"
git push -u origin feature/stability-layer
```

## Wat er in deze zip zit

Nieuw:
- `livefire/crash.py` — sys.excepthook + Qt message handler + log-writer
- `livefire/autosave.py` — AutosaveManager, atomic write, recovery-helpers
- `tests/test_crash.py` (7 tests)
- `tests/test_autosave.py` (11 tests)
- `tests/test_showtime_lock.py` (4 tests)

Gewijzigd:
- `livefire/__init__.py` — APP_VERSION 0.5.1 → 0.5.2
- `livefire/__main__.py` — vroege `crash_mod.install_handlers()`
- `livefire/ui/transport.py` — Showtime-toggle (🔓/🔒)
- `livefire/ui/mainwindow.py` — gate, autosave-wiring, recovery-prompts,
  crash-dialog via QueuedConnection-signal
- `CHANGELOG.md` — v0.5.2-entry

## Verwachte test-uitkomst

```
======================== 164 passed, 1 skipped in ~6s ========================
```

De 1 skipped zat al in de baseline (audio-engine test die een output-
device verwacht); de 22 nieuwe tests zitten in test_crash.py +
test_autosave.py + test_showtime_lock.py.
