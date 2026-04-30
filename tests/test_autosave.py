"""Tests voor de autosave-laag.

Focus: pad-resolutie (genoemd vs onbenoemd), atomic write (geen half-
bestand bij crash), recovery-detectie (autosave nieuwer dan workspace),
cleanup na manual save, en het 'niets-te-doen-als-niet-dirty'-pad."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from livefire.autosave import (
    AUTOSAVE_SUFFIX,
    AutosaveManager,
    autosave_path_for,
    find_recoverable_for,
    _atomic_write_json,
)
from livefire.cues import Cue, CueType
from livefire.workspace import Workspace


# ---- pad-resolutie ---------------------------------------------------------

def test_path_for_named_workspace(tmp_path: Path) -> None:
    ws_path = tmp_path / "show.livefire"
    out = autosave_path_for(ws_path, session_id="abcdef")
    assert out == tmp_path / f"show.livefire{AUTOSAVE_SUFFIX}"


def test_path_for_untitled_uses_session_id(tmp_path: Path, monkeypatch) -> None:
    # _untitled_dir leunt op QStandardPaths; voor een unit-test
    # monkeypatchen we 'm naar een tmp-locatie zodat we niet schrijven
    # naar de echte AppData.
    import livefire.autosave as autosave_mod
    monkeypatch.setattr(autosave_mod, "_untitled_dir", lambda: tmp_path)
    out = autosave_path_for(None, session_id="cafebabe")
    assert out.parent == tmp_path
    assert out.name == f"untitled-cafebabe.livefire{AUTOSAVE_SUFFIX}"


# ---- atomic write ---------------------------------------------------------

def test_atomic_write_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    target.write_text("OLD CONTENT", encoding="utf-8")
    _atomic_write_json(target, {"new": "data"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": "data"}


def test_atomic_write_no_tmp_left_behind(tmp_path: Path) -> None:
    target = tmp_path / "y.json"
    _atomic_write_json(target, {"k": 1})
    # Geen .tmp meer over na succesvolle write.
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


# ---- manager: dirty-elision ------------------------------------------------

def _ws_with_one_cue(path: Path | None = None) -> Workspace:
    ws = Workspace(name="Test")
    ws.path = path
    ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number="1", name="m"))
    return ws


def test_manager_writes_on_first_tick(tmp_path: Path, qt_app) -> None:
    ws = _ws_with_one_cue(path=tmp_path / "show.livefire")
    am = AutosaveManager(parent=None, interval_ms=10_000)
    am.attach_workspace(ws)
    am._tick()  # forceer
    target = autosave_path_for(ws.path, am.session_id)
    assert target.is_file()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["cues"][0]["name"] == "m"


def test_manager_skips_when_clean_and_already_written(
    tmp_path: Path, qt_app
) -> None:
    ws = _ws_with_one_cue(path=tmp_path / "show.livefire")
    am = AutosaveManager(parent=None, interval_ms=10_000)
    am.attach_workspace(ws)
    am._tick()  # eerste write
    target = autosave_path_for(ws.path, am.session_id)
    first_mtime = target.stat().st_mtime
    # Reset dirty (zoals Workspace.save() doet) en tik nogmaals.
    ws.dirty = False
    # Sleep een fractie zodat een eventuele write een nieuwe mtime
    # zou geven (resolutie kan op sommige FS 1s zijn).
    os.utime(target, (first_mtime - 1, first_mtime - 1))
    expected_mtime = target.stat().st_mtime
    am._tick()
    assert target.stat().st_mtime == expected_mtime


def test_manager_writes_again_when_dirty(tmp_path: Path, qt_app) -> None:
    ws = _ws_with_one_cue(path=tmp_path / "show.livefire")
    am = AutosaveManager(parent=None, interval_ms=10_000)
    am.attach_workspace(ws)
    am._tick()
    target = autosave_path_for(ws.path, am.session_id)
    # Wijzig de workspace en zet de mtime van het autosave-bestand
    # op een vast moment in het verleden, zodat we kunnen zien dat
    # er opnieuw geschreven is.
    ws.add_cue(Cue(cue_type=CueType.MEMO, cue_number="2", name="m2"))
    old = target.stat().st_mtime - 5
    os.utime(target, (old, old))
    am._tick()
    assert target.stat().st_mtime > old


def test_manager_clear_removes_sidecar(tmp_path: Path, qt_app) -> None:
    ws = _ws_with_one_cue(path=tmp_path / "show.livefire")
    am = AutosaveManager(parent=None, interval_ms=10_000)
    am.attach_workspace(ws)
    am._tick()
    target = autosave_path_for(ws.path, am.session_id)
    assert target.is_file()
    am.clear_for_current()
    assert not target.exists()


# ---- recovery -------------------------------------------------------------

def test_recovery_detects_newer_autosave(tmp_path: Path, qt_app) -> None:
    ws = _ws_with_one_cue(path=tmp_path / "show.livefire")
    ws.save()  # creëer het echte bestand
    am = AutosaveManager(parent=None, interval_ms=10_000)
    am.attach_workspace(ws)
    # Markeer dirty en force een autosave-tick zodat de sidecar verschijnt
    ws.dirty = True
    am._tick()
    target = autosave_path_for(ws.path, am.session_id)
    # Maak workspace ouder dan de autosave (zou normaal zo zijn na
    # crash: workspace is oud, autosave is recenter).
    older = target.stat().st_mtime - 10
    os.utime(ws.path, (older, older))
    rec = find_recoverable_for(ws.path)
    assert rec is not None
    assert rec.autosave_path == target
    assert rec.original_path == ws.path
    assert rec.is_untitled is False


def test_recovery_skips_when_autosave_older(tmp_path: Path, qt_app) -> None:
    ws = _ws_with_one_cue(path=tmp_path / "show.livefire")
    ws.save()
    am = AutosaveManager(parent=None, interval_ms=10_000)
    am.attach_workspace(ws)
    ws.dirty = True
    am._tick()
    target = autosave_path_for(ws.path, am.session_id)
    # Autosave ouder dan workspace = niets te recoveren.
    older = ws.path.stat().st_mtime - 10
    os.utime(target, (older, older))
    assert find_recoverable_for(ws.path) is None


def test_recovery_no_sidecar_returns_none(tmp_path: Path) -> None:
    ws_path = tmp_path / "show.livefire"
    ws_path.write_text("{}", encoding="utf-8")
    assert find_recoverable_for(ws_path) is None
