"""Workspace save/load roundtrip + format-migratie tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from livefire import WORKSPACE_FORMAT_VERSION
from livefire.cues import Cue, CueType, ContinueMode
from livefire.workspace import Workspace


def test_roundtrip_preserves_all_cue_types(tmp_path: Path):
    ws = Workspace(name="roundtrip")
    ws.add_cue(Cue(cue_type=CueType.AUDIO, name="intro", volume_db=-6.0,
                   loops=2, audio_start_offset=0.5,
                   audio_fade_in=1.5, audio_fade_out=2.0))
    ws.add_cue(Cue(cue_type=CueType.WAIT, name="pauze", wait_duration=3.0))
    target = ws.cues[0].id
    ws.add_cue(Cue(cue_type=CueType.FADE, name="outfade",
                   target_cue_id=target, fade_target_db=-60.0,
                   duration=3.0, fade_stops_target=True))
    ws.add_cue(Cue(cue_type=CueType.STOP, name="stop alles"))
    ws.add_cue(Cue(cue_type=CueType.GROUP, name="groep"))
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="memo",
                   notes="Toegang niet vergeten!"))
    ws.add_cue(Cue(cue_type=CueType.START, name="start",
                   target_cue_id=target,
                   continue_mode=ContinueMode.AUTO_CONTINUE,
                   trigger_osc="/livefire/go/start"))
    ws.add_cue(Cue(cue_type=CueType.VIDEO, name="movie",
                   file_path="C:/tmp/movie.mp4",
                   video_output_screen=1,
                   video_fade_in=0.5,
                   video_fade_out=1.5,
                   video_start_offset=2.0,
                   video_end_offset=8.5,
                   volume_db=-12.0))
    ws.add_cue(Cue(cue_type=CueType.PRESENTATION, name="deck",
                   file_path="C:/tmp/deck.pptx",
                   presentation_action="open"))
    ws.add_cue(Cue(cue_type=CueType.PRESENTATION, name="slide 3",
                   presentation_action="goto",
                   presentation_slide=3))

    p = tmp_path / "test.livefire"
    ws.save(p)
    loaded = Workspace.load(p)

    assert len(loaded.cues) == len(ws.cues)
    for orig, got in zip(ws.cues, loaded.cues):
        assert orig.id == got.id
        assert orig.cue_type == got.cue_type
        assert orig.name == got.name
        assert orig.volume_db == got.volume_db
        assert orig.loops == got.loops
        assert orig.target_cue_id == got.target_cue_id
        assert orig.fade_stops_target == got.fade_stops_target
        assert orig.continue_mode == got.continue_mode
        assert orig.audio_fade_in == got.audio_fade_in
        assert orig.audio_fade_out == got.audio_fade_out
        assert orig.trigger_osc == got.trigger_osc
        assert orig.video_output_screen == got.video_output_screen
        assert orig.video_fade_in == got.video_fade_in
        assert orig.video_fade_out == got.video_fade_out
        assert orig.video_start_offset == got.video_start_offset
        assert orig.video_end_offset == got.video_end_offset
        assert orig.presentation_action == got.presentation_action
        assert orig.presentation_slide == got.presentation_slide


def test_save_writes_current_format_version(tmp_path: Path):
    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="x"))
    p = ws.save(tmp_path / "v.livefire")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["format_version"] == WORKSPACE_FORMAT_VERSION


def test_migration_v1_to_current(tmp_path: Path):
    # Simuleer een v0.2.x file met format_version=1 en oude fade_volume_db
    p = tmp_path / "old.livefire"
    p.write_text(json.dumps({
        "format_version": 1,
        "app_version": "0.2.0",
        "name": "oud",
        "cues": [{
            "id": "abc",
            "cue_type": "Fade",
            "name": "oude fade",
            "fade_volume_db": -20.0,      # oude veldnaam
            "target_cue_id": "xyz",
        }],
    }), encoding="utf-8")

    ws = Workspace.load(p)
    assert len(ws.cues) == 1
    assert ws.cues[0].fade_target_db == -20.0


def test_move_cue(tmp_path: Path):
    ws = Workspace()
    a = Cue(cue_type=CueType.MEMO, name="a")
    b = Cue(cue_type=CueType.MEMO, name="b")
    c = Cue(cue_type=CueType.MEMO, name="c")
    for x in (a, b, c):
        ws.add_cue(x)

    assert ws.move(a.id, 1)
    assert [x.name for x in ws.cues] == ["b", "a", "c"]
    assert ws.move(c.id, -1)
    assert [x.name for x in ws.cues] == ["b", "c", "a"]
    # Niet voorbij het einde
    assert not ws.move(a.id, 1)


def test_renumber():
    ws = Workspace()
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="a"))
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="b"))
    ws.add_cue(Cue(cue_type=CueType.MEMO, name="c"))
    ws.renumber(start=10, step=5)
    assert [c.cue_number for c in ws.cues] == ["10", "15", "20"]


def test_unknown_format_version_raises(tmp_path: Path):
    p = tmp_path / "future.livefire"
    p.write_text(json.dumps({
        "format_version": 99,
        "cues": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        Workspace.load(p)
