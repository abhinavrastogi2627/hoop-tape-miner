"""Movement sessions: segments and reel plan, folder detection, scan reuse, sheets, summary gate, steps."""
import json

import numpy as np
import pytest

from hoop_tape_miner import game_config as gc
from hoop_tape_miner import move_new as MN
from hoop_tape_miner import movement as M


def seg(**kw):
    return dict(dict(kind="layup", view="side", source="a.mp4", **{"from": 0, "to": 4.5}), **kw)


def test_secs():
    assert M.secs("31:46.5") == 1906.5
    assert M.secs("1:02:03") == 3723
    assert M.secs(12) == 12.0


def test_reel_plan_offsets():
    segs = MN.reel_plan([seg(), seg(source="b.mp4", **{"from": "00:10", "to": "00:13"})],
                        {"a.mp4": 60, "b.mp4": 60}, {"a.mp4": 30, "b.mp4": 30})
    assert [s["id"] for s in segs] == ["S01", "S02"]
    assert (segs[0]["reel_from"], segs[0]["reel_to"]) == (0, 4.5)
    assert (segs[1]["reel_from"], segs[1]["reel_to"]) == (4.5, 7.5)


def test_reel_plan_rejects_bad_window():
    with pytest.raises(ValueError, match="S01"):
        MN.reel_plan([seg(to=70)], {"a.mp4": 60}, {"a.mp4": 30})
    with pytest.raises(ValueError, match="source not found"):
        MN.reel_plan([seg(source="missing.mp4")], {"a.mp4": 60}, {"a.mp4": 30})
    with pytest.raises(ValueError, match="kind"):
        MN.reel_plan([seg(kind="walk")], {"a.mp4": 60}, {"a.mp4": 30})


def test_reel_plan_fps():
    s = MN.reel_plan([seg()], {"a.mp4": 60}, {"a.mp4": 240})[0]
    assert s["scan_fps"] == 120 and s["real_fps"] == 120
    s = MN.reel_plan([seg(slowmo=8)], {"a.mp4": 60}, {"a.mp4": 30})[0]  # exported 240 fps slow motion at 30 fps
    assert s["scan_fps"] == 15 and s["real_fps"] == 120


def test_create_and_extend(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path / "ws"))
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    built = []

    def builder(segs, out):
        built.append([s["id"] for s in segs])
        out.write_bytes(b"reel")
        return [M.secs(s["to"]) - M.secs(s["from"]) + 0.01 for s in segs]

    prober = lambda p: dict(duration=20.0, fps=30.0)
    f = MN.create([seg(source=str(src), to=5)], "17", "2026-10-20", prober=prober, builder=builder)
    m = M.load(f)
    assert m["kind"] == "movement" and f.name == "2026-10-20"
    assert m["segments"][0]["reel_to"] == 5.01  # placed by the real part length
    MN.create([seg(source=str(src), **{"from": 6, "to": 8})], into=f, prober=prober, builder=builder)
    m = M.load(f)
    assert [s["id"] for s in m["segments"]] == ["S01", "S02"] and built[-1] == ["S01", "S02"]
    assert m["segments"][1]["reel_from"] == 5.01
    assert gc.load_game(f)["kind"] == "movement"
    assert gc.is_movement(gc.load_game(f)) and gc.is_personal(gc.load_game(f))
    assert not gc.is_personal({"kind": "game"})
