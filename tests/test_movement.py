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


# ---- move-scan ---------------------------------------------------------------------------------------------

def _session(tmp_path, segments):
    f = tmp_path / "mv"
    f.mkdir()
    M.save(f, dict(kind="movement", player="17", date="2026-10-20", run=str(tmp_path / "run"),
                   video=str(tmp_path / "reel.mp4"), segments=segments))
    return f


def _fake_scanner(calls):
    from test_gait import runner

    def scanner(video, fps, ball, t0, t1):
        calls.append(dict(video=str(video), fps=fps, ball=ball, t0=t0, t1=t1))
        t, kp, conf, *_ = runner(fps=fps, dur=t1 - t0)
        n = len(t)
        boxes = np.full((n, 6, 4), np.nan)
        boxes[:, 0] = (300, 100, 700, 470)
        kps = np.full((n, 6, 17, 2), np.nan)
        kps[:, 0] = kp
        confs = np.zeros((n, 6, 17))
        confs[:, 0] = conf
        return dict(t=t + t0, boxes=boxes, kps=kps, confs=confs, balls=np.full((n, 4, 2), np.nan),
                    size=np.array([1280, 720]))
    return scanner


def test_scan_skips_done(tmp_path):
    from hoop_tape_miner import move_scan as MS
    f = _session(tmp_path, [dict(id="S01", kind="sprint", view="side", source="a.mp4", **{"from": 10, "to": 13},
                                 fps=30, scan_fps=30)])
    calls = []
    assert MS.scan_segments(f, scanner=_fake_scanner(calls)) == ["S01"]
    g = json.loads((tmp_path / "run" / "gait" / "S01.json").read_text())
    assert g["metrics_version"] == 1 and g["direction"] == 1 and len(g["contacts"]) >= 6
    assert all(10 <= c["on"] <= 13 for c in g["contacts"])  # source seconds
    assert MS.scan_segments(f, scanner=_fake_scanner(calls)) == [] and len(calls) == 1
    assert len(json.loads((tmp_path / "run" / "gait.json").read_text())) == 1


def test_scan_fps_cap(tmp_path):
    from hoop_tape_miner import move_scan as MS
    seg = MN.reel_plan([dict(kind="sprint", view="side", source="a.mp4", **{"from": 0, "to": 2})],
                       {"a.mp4": 5}, {"a.mp4": 240})[0]
    f = _session(tmp_path, [seg])
    calls = []
    MS.scan_segments(f, scanner=_fake_scanner(calls))
    assert calls[0]["fps"] == 120 and calls[0]["ball"] is False
    g = json.loads((tmp_path / "run" / "gait" / "S01.json").read_text())
    assert g["clip"]["contact_ok"] and any(s["contact_s"] for s in g["steps"])


def test_game_segment_no_metrics(tmp_path):
    from hoop_tape_miner import move_scan as MS
    f = _session(tmp_path, [dict(id="G1", kind="game", view="game", source="g.mp4", **{"from": 0, "to": 4})])
    calls = []
    MS.scan_segments(f, scanner=_fake_scanner(calls))
    assert calls == []
    assert json.loads((tmp_path / "run" / "gait" / "G1.json").read_text())["metrics"] is None


def test_scan_measurable_side_only(tmp_path):
    from hoop_tape_miner import move_scan as MS
    f = _session(tmp_path, [dict(id="S01", kind="sprint", view="side", source="a.mp4", **{"from": 0, "to": 3}),
                            dict(id="S02", kind="sprint", view="behind", source="a.mp4", **{"from": 0, "to": 3})])
    MS.scan_segments(f, scanner=_fake_scanner([]))
    g = {s: json.loads((tmp_path / "run" / "gait" / f"{s}.json").read_text()) for s in ("S01", "S02")}
    assert g["S01"]["measurable"] is True and g["S02"]["measurable"] is False


# ---- move-sheets -------------------------------------------------------------------------------------------

def test_draw_overlay_shape():
    from test_gait import runner
    from hoop_tape_miner import move_sheets as MSH
    _, kp, conf, *_ = runner()
    frame = np.zeros((720, 1280, 3), np.uint8)
    out = MSH.draw_overlay(frame, kp[0], conf[0], {"angles": True, "tags": ["TD L"]})
    assert out.shape == frame.shape and out.any() and not frame.any()  # drawn on a copy
    conf0 = np.zeros_like(conf[0])
    assert not MSH.draw_overlay(frame, kp[0], conf0).any()  # nothing confident, nothing drawn


def test_brief_groups():
    from hoop_tape_miner import move_sheets as MSH
    segs = [dict(id=f"L{k:02d}") for k in range(1, 18)]
    g = MSH.groups(segs, 8)
    assert [len(x) for x in g] == [6, 6, 5] and [s["id"] for x in g for s in x] == [s["id"] for s in segs]
    assert MSH.groups([], 8) == [] and len(MSH.groups(segs[:8], 8)) == 1


def test_key_and_strip_times():
    from hoop_tape_miner import move_sheets as MSH
    lay = dict(kind="layup", view="side", **{"from": 100, "to": 104})
    ts = MSH.key_times(lay, {"release": 102.5})
    assert ts[0] == 101.0 and ts[-1] == 103.3 and len(ts) == 24
    run = dict(kind="sprint", view="behind", **{"from": 10, "to": 14})
    assert len(MSH.key_times(run, {})) == MSH.KEY_N
    assert MSH.strip_times(run, {}, np.arange(10, 14, 1 / 120)) == []  # side view only
    pose_t = np.arange(100, 104, 1 / 120)
    st = MSH.strip_times(lay, {"release": 102.5, "layup": {"takeoff_t": 102.3}}, pose_t)
    assert len(st) == MSH.STRIP_MAX and st[0] >= 100.8 - 1e-6 and st[-1] <= 102.4 + 1e-6
    st = MSH.strip_times(dict(lay, kind="sprint"), {}, np.arange(100, 104, 1 / 30))
    assert len(st) == 61 and st[-1] <= 102 + 1e-6


def test_reel_transform():
    from hoop_tape_miner import move_sheets as MSH
    s, ox, oy, cx, cy = MSH.reel_transform({}, (1920, 1080))
    assert (round(s, 4), ox, oy, cx, cy) == (0.6667, 0, 0, 0, 0)
    s, ox, oy, cx, cy = MSH.reel_transform({"crop": [0.5, 0, 0.5, 1]}, (1920, 1080))  # 960x1080 -> 640x720
    assert (round(s, 4), round(ox), oy, cx) == (0.6667, 320, 0, 960)


def test_write_brief_fills_template(tmp_path):
    from hoop_tape_miner import move_sheets as MSH
    segs = [dict(id="L01", kind="layup", view="behind", source="/v/session.mp4", **{"from": "31:44", "to": "31:48"},
                 reel_from=0, reel_to=4),
            dict(id="G1", kind="game", view="game", source="/v/game.mp4", **{"from": 10, "to": 14},
                 reel_from=4, reel_to=8)]
    m = dict(kind="movement", player="17", name="M", look="black shirt", plan="layups", segments=segs)
    gaits = {"L01": {"measurable": False, "visible_share": 0.9}, "G1": {"metrics": None, "measurable": False}}
    p = MSH.write_brief(tmp_path, m, tmp_path, "g1", segs, {"L01": {"keys": "keys_L01.jpg"}}, gaits)
    text = p.read_text(encoding="utf8")
    assert "{{" not in text and "<!--" not in text
    assert "### L01 · layup · view behind" in text and "keys_L01.jpg" in text and "black shirt" in text
    assert "no running or layup numbers" in text and "review only (game camera)" in text


# ---- move-summary ------------------------------------------------------------------------------------------

def _gait(sid="S01", kind="sprint", view="side", lean=55.0, contacts=(1.0, 1.25, 1.5, 1.75), fps=120.0, **kw):
    steps = [dict(t=c, trunk_lean=lean, shin=35.0, touchdown_ahead=0.0, step_time=0.25, contact_s=0.19)
             for c in contacts]
    return dict(id=sid, kind=kind, view=view, measurable=view == "side", real_fps=fps, metrics_version=1,
                contacts=[dict(foot="LR"[k % 2], on=c) for k, c in enumerate(contacts)], steps=steps, **kw)


def test_gate_hides_metric():
    from hoop_tape_miner import move_summary as MS
    g = {"S01": _gait()}
    good = MS.validate(g, {"S01": {"contacts": [{"foot": "L", "on": 1.0}, {"foot": "R", "on": 1.25},
                                                {"foot": "L", "on": 1.5}, {"foot": "R", "on": 1.75}]}})
    assert good["S01"]["pass"]
    m = MS.metrics(g, good)
    assert m["sprint/side/trunk_lean@accel"]["shown"] and m["sprint/side/trunk_lean@accel"]["mean"] == 55.0
    assert m["sprint/side/cadence_spm@accel"]["mean"] == 240.0
    bad = MS.validate(g, {"S01": {"contacts": [{"foot": "L", "on": 1.1}, {"foot": "R", "on": 1.37}]}})
    assert not bad["S01"]["pass"]
    m = MS.metrics(g, bad)
    assert not m["sprint/side/trunk_lean@accel"]["shown"]
    assert not MS.metrics(g, {})["sprint/side/trunk_lean@accel"]["shown"]  # never checked -> not shown
    sm = dict(player="17", name="", date="2026-10-20", headline=dict(segments=1, side=1, reviewed=0, seen=0,
              hypotheses=0, good=0, validated=False, shown_metrics=0), not_measurable=[], not_reviewed=["S01"],
              faults=[], metrics=m, validation=bad, progress=[], notes=[])
    text = MS.facts(sm)
    assert "| sprint/side/trunk_lean@accel |" not in text and "No measurement is shown" in text


def test_behind_view_no_metrics():
    from hoop_tape_miner import move_summary as MS
    assert MS.metrics({"S01": _gait(view="behind")}, {}) == {}
    assert MS.validate({"S01": _gait(view="behind")}, {"S01": {"contacts": [{"foot": "L", "on": 1.0}]}}) == {}


def test_faults_merge():
    from hoop_tape_miner import move_summary as MS
    gaits = {"L01": _gait("L01", "layup", "behind"), "L02": _gait("L02", "layup", "behind"),
             "S01": _gait("S01", "sprint", "side")}
    r1 = {"segments": [{"id": "L01", "identity_ok": True, "faults": [
        {"kb": "MV-landing", "status": "seen", "t": "31:46.2", "confidence": "high", "note": "stiff"},
        {"kb": "MV-accel-posture", "status": "seen", "t": "31:45.0", "confidence": "medium", "note": "waist fold"}]}]}
    r2 = {"segments": [{"id": "L02", "identity_ok": True, "faults": [
        {"kb": "MV-landing", "status": "seen", "t": "32:40.0", "confidence": "low"}],
        "good": [{"kb": "MV-one-foot-takeoff", "t": "32:39.8", "note": "free knee up"}]},
        {"id": "S01", "identity_ok": False, "faults": [{"kb": "MV-landing", "status": "seen", "t": "1:00"}]}]}
    rows = {r["kb"]: r for r in MS.faults([r1, r2], gaits)}
    assert rows["MV-landing"]["seen"] == ["L01", "L02"] and rows["MV-landing"]["times"] == ["31:46.2", "32:40.0"]
    assert rows["MV-accel-posture"]["status"] == "hypothesis"  # running fault from a behind camera
    assert rows["MV-one-foot-takeoff"]["status"] == "good"


def test_facts_unknown_not_zero():
    from hoop_tape_miner import move_summary as MS
    assert MS.unk(None) == "unknown" and MS.unk(0.0) == "0.00"
    m = {"sprint/side/trunk_lean@accel": dict(values={"S01": 50.0, "S02": 52.0}, band=(48, 64), kb="MV-accel-posture",
                                              unit="°", metric="trunk_lean", phase="accel", shown=True, reason="",
                                              n=2, mean=51.0, sd=None)}
    sm = dict(player="17", name="M", date="2026-10-20", headline=dict(segments=2, side=2, reviewed=2, seen=0,
              hypotheses=0, good=0, validated=True, shown_metrics=1), not_measurable=[], not_reviewed=[],
              faults=[], metrics=m, validation={}, progress=[], notes=[])
    assert "| sprint/side/trunk_lean@accel | 51.00 ° | unknown | 2 | 48-64 ° | MV-accel-posture |" in MS.facts(sm)


def test_progress_matches_only_same_kind(tmp_path):
    from hoop_tape_miner import move_summary as MS
    root = tmp_path / "movement"
    for d, ver, view in (("2026-09-01", 1, "behind"), ("2026-09-15", 0, "side"), ("2026-10-01", 1, "side")):
        f = root / d
        f.mkdir(parents=True)
        M.save(f, dict(kind="movement", segments=[]))
        key = f"sprint/{view}/trunk_lean@accel"
        (f / "summary.json").write_text(json.dumps(dict(metrics_version=ver, metrics={
            key: dict(shown=True, mean=40.0)})))
    now = root / "2026-10-20"
    now.mkdir()
    M.save(now, dict(kind="movement", segments=[]))
    rows = MS.progress(now, {"sprint/side/trunk_lean@accel": dict(shown=True, mean=50.0)})
    assert rows == [dict(session="2026-10-01", metric="sprint/side/trunk_lean@accel", before=40.0, now=50.0,
                         delta=10.0)]
