"""Tests voor echte group-cues: workspace-tree-helpers, controller
group-firing in de vier modes (list / first-then-list / parallel /
random), en stop-cascade naar nakomelingen.

We gebruiken een controller-stub (zonder echte engines) zodat we de
group-orchestratie kunnen testen zonder audio/video/dmx te starten.
Voor de chain-tests roepen we ``_advance_group_chain`` direct aan i.p.v.
te wachten op een tick — dat houdt de test deterministisch."""

from __future__ import annotations

import pytest

from livefire.cues import Cue, CueType, ContinueMode
from livefire.workspace import Workspace


# ---- workspace-tree helpers ------------------------------------------------


def _make_ws_with_group() -> tuple[Workspace, dict[str, Cue]]:
    """Bouw een workspace met de volgende structuur:

        0  cue A (top-level)
        1  cue G1 (group, group_mode default "list")
        2  cue B (child of G1)
        3  cue C (child of G1)
        4  cue D (top-level, ná G1)

    Children komen direct na hun parent — dat is de invariant die
    cuelist-rendering en first_index_after_group op vertrouwen.
    """
    ws = Workspace()
    a = Cue(cue_type=CueType.MEMO, name="a")
    g1 = Cue(cue_type=CueType.GROUP, name="g1")
    b = Cue(cue_type=CueType.MEMO, name="b", parent_group_id=g1.id)
    c = Cue(cue_type=CueType.MEMO, name="c", parent_group_id=g1.id)
    d = Cue(cue_type=CueType.MEMO, name="d")
    for cue in (a, g1, b, c, d):
        ws.add_cue(cue)
    return ws, {"a": a, "g1": g1, "b": b, "c": c, "d": d}


def test_children_of_returns_direct_children_only() -> None:
    ws, cues = _make_ws_with_group()
    children = ws.children_of(cues["g1"].id)
    assert [c.name for c in children] == ["b", "c"]
    assert ws.children_of(cues["a"].id) == []


def test_descendants_of_walks_nested_groups() -> None:
    ws, cues = _make_ws_with_group()
    # Voeg een nested group binnen G1 toe met één child
    g2 = Cue(cue_type=CueType.GROUP, name="g2", parent_group_id=cues["g1"].id)
    e = Cue(cue_type=CueType.MEMO, name="e", parent_group_id=g2.id)
    ws.add_cue(g2, index=ws.index_of(cues["c"].id) + 1)
    ws.add_cue(e, index=ws.index_of(g2.id) + 1)

    descendants = ws.descendants_of(cues["g1"].id)
    names = {c.name for c in descendants}
    assert names == {"b", "c", "g2", "e"}


def test_first_index_after_group_skips_descendants() -> None:
    ws, cues = _make_ws_with_group()
    # Group G1 staat op index 1, descendants op 2 en 3, dus eerste cue
    # ná de hele group-block is index 4 (cue D).
    assert ws.first_index_after_group(cues["g1"].id) == 4


def test_first_index_after_group_at_end_of_list() -> None:
    """Group als laatste regel → first_index_after_group = len(cues)."""
    ws = Workspace()
    g = Cue(cue_type=CueType.GROUP, name="g")
    child = Cue(cue_type=CueType.MEMO, name="child", parent_group_id=g.id)
    ws.add_cue(g)
    ws.add_cue(child)
    assert ws.first_index_after_group(g.id) == 2


def test_is_in_group_recursive() -> None:
    ws = Workspace()
    g_outer = Cue(cue_type=CueType.GROUP, name="outer")
    g_inner = Cue(cue_type=CueType.GROUP, name="inner",
                  parent_group_id=g_outer.id)
    leaf = Cue(cue_type=CueType.MEMO, name="leaf",
               parent_group_id=g_inner.id)
    other = Cue(cue_type=CueType.MEMO, name="other")
    for c in (g_outer, g_inner, leaf, other):
        ws.add_cue(c)

    assert ws.is_in_group(leaf.id, g_inner.id) is True
    # Recursief: leaf zit ook in outer, want inner zit in outer.
    assert ws.is_in_group(leaf.id, g_outer.id) is True
    assert ws.is_in_group(other.id, g_outer.id) is False


# ---- workspace-roundtrip --------------------------------------------------


def test_parent_group_id_roundtrips_through_save_load(tmp_path) -> None:
    ws, cues = _make_ws_with_group()
    target = tmp_path / "groups.livefire"
    ws.save(target)
    loaded = Workspace.load(target)
    g1_id = cues["g1"].id
    children = [c for c in loaded.cues if c.parent_group_id == g1_id]
    assert len(children) == 2
    assert {c.name for c in children} == {"b", "c"}


# ---- controller stub ------------------------------------------------------


def _make_stub_controller(ws: Workspace):
    """PlaybackController zonder echte engines. _start_cue krijgt z'n
    bookkeeping (in_group_chain, _Running entry), maar fired-list houden
    we expliciet bij zodat tests kunnen verifiëren wat er afging."""
    from PyQt6.QtCore import QObject
    from livefire.playback.controller import PlaybackController, _Running
    import time

    class _Stub(PlaybackController):
        def __init__(self, ws):
            QObject.__init__(self)
            self.workspace = ws
            self._running = {}
            self._playhead_index = 0
            self._group_chain = {}
            self._group_chain_owner = {}
            self.fired: list[tuple[str, bool]] = []  # (cue_id, in_group_chain)

        def _start_cue(self, cue, in_group_chain: bool = False):  # type: ignore[override]
            self.fired.append((cue.id, in_group_chain))
            r = _Running(cue=cue, started_at=time.monotonic(), phase="action",
                         phase_started_at=time.monotonic(),
                         in_group_chain=in_group_chain)
            self._running[cue.id] = r

        def _stop_running(self, cue_id, finished):  # type: ignore[override]
            r = self._running.pop(cue_id, None)
            if r is None:
                return
            r.cue.state = "finished" if finished else "idle"
            if finished and cue_id in self._group_chain_owner:
                self._advance_group_chain(cue_id)

    return _Stub(ws)


# ---- controller: group modes ----------------------------------------------


def test_list_mode_moves_playhead_to_first_child_without_firing(qt_app) -> None:
    ws, cues = _make_ws_with_group()
    cues["g1"].group_mode = "list"
    ctrl = _make_stub_controller(ws)
    ctrl._fire_group(cues["g1"])

    # Geen children gevuurd — alleen playhead verplaatst naar B (index 2)
    assert [cid for cid, _ in ctrl.fired] == []
    assert ctrl.playhead_index == ws.index_of(cues["b"].id)


def test_parallel_mode_fires_all_children_at_once(qt_app) -> None:
    ws, cues = _make_ws_with_group()
    cues["g1"].group_mode = "parallel"
    ctrl = _make_stub_controller(ws)
    ctrl._fire_group(cues["g1"])

    # B + C beide in de fired-lijst, geen group-chain marker
    fired_ids = [cid for cid, _ in ctrl.fired]
    assert set(fired_ids) == {cues["b"].id, cues["c"].id}
    # Playhead voorbij de hele group-block (= index 4 = cue D)
    assert ctrl.playhead_index == 4


def test_random_mode_fires_one_child(qt_app) -> None:
    ws, cues = _make_ws_with_group()
    cues["g1"].group_mode = "random"
    ctrl = _make_stub_controller(ws)
    ctrl._fire_group(cues["g1"])

    fired_ids = [cid for cid, _ in ctrl.fired]
    assert len(fired_ids) == 1
    assert fired_ids[0] in {cues["b"].id, cues["c"].id}
    assert ctrl.playhead_index == 4


def test_first_then_list_mode_chains_children(qt_app) -> None:
    ws, cues = _make_ws_with_group()
    cues["g1"].group_mode = "first-then-list"
    ctrl = _make_stub_controller(ws)
    ctrl._fire_group(cues["g1"])

    # Eerste child (B) gevuurd met in_group_chain=True
    assert ctrl.fired[0] == (cues["b"].id, True)
    assert ctrl.playhead_index == 4

    # B finisht → C wordt automatisch gevuurd via _advance_group_chain
    ctrl._stop_running(cues["b"].id, finished=True)
    assert ctrl.fired[-1] == (cues["c"].id, True)

    # C finisht → keten leeg, geen extra fires
    ctrl._stop_running(cues["c"].id, finished=True)
    assert [cid for cid, _ in ctrl.fired] == [cues["b"].id, cues["c"].id]


def test_first_then_list_does_not_chain_on_manual_stop(qt_app) -> None:
    """Een handmatige stop midden in een first-then-list-chain mag de
    rest niet alsnog triggeren — alleen ``finished=True`` chain't door."""
    ws, cues = _make_ws_with_group()
    cues["g1"].group_mode = "first-then-list"
    ctrl = _make_stub_controller(ws)
    ctrl._fire_group(cues["g1"])
    # B handmatig stoppen (finished=False) → keten breekt
    ctrl._stop_running(cues["b"].id, finished=False)
    assert ctrl.fired == [(cues["b"].id, True)]


def test_empty_group_is_noop(qt_app) -> None:
    """Een group zonder children mag geen crash + geen fires opleveren."""
    ws = Workspace()
    g = Cue(cue_type=CueType.GROUP, name="empty", group_mode="parallel")
    ws.add_cue(g)
    ctrl = _make_stub_controller(ws)
    duration = ctrl._fire_group(g)
    assert duration == 0.0
    assert ctrl.fired == []
