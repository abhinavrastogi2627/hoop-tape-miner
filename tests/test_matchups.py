"""Defender distance at the shot and who-guarded-whom, from synthetic court tracks."""
import json

import numpy as np
import pandas as pd

from hoop_tape_miner import matchups as M


def tracks_of(paths: dict, t0=0.0, t1=10.0, fps=10):
    """paths: {(team, number|None, track): fn(t) -> (x, y)} -> DataFrame like tracks.pkl."""
    rows = []
    for i, t in enumerate(np.round(np.arange(t0, t1 + 1e-9, 1 / fps), 1)):
        for (team, num, tid), fn in paths.items():
            p = fn(t)
            if p is None:
                continue
            rows.append(dict(frame=i * 6, t=float(t), team=team, track=tid, number=num, cx=p[0], cy=p[1],
                             cx_s=p[0], cy_s=p[1]))
    return pd.DataFrame(rows)


def at(x, y):
    return lambda t: (x, y)


SCENE = {("us", "7", 1): at(24, 7.5), ("us", "9", 2): at(20, 2), ("us", "4", 3): at(20, 13),
         ("them", "5", 11): at(24.8, 7.5), ("them", "8", 12): at(21, 2.5), ("them", None, 13): at(19, 12)}


def test_bins():
    assert M.bin_of(0.5) == "tight" and M.bin_of(1.5) == "contested" and M.bin_of(3.0) == "open"
    assert M.bin_of(None) is None


def test_defender_distance_at_shot():
    tr = tracks_of(SCENE)
    d = M.defender_distance(tr, "us", "7", 5.0)
    assert d["dist_m"] == 0.8 and d["bin"] == "tight" and d["defender"] == "5" and d["opp_tracked"] == 3


def test_unknown_without_shooter_or_enough_defenders():
    tr = tracks_of(SCENE)
    assert M.defender_distance(tr, "us", "12", 5.0)["bin"] is None  # shooter not tracked
    assert M.defender_distance(tr, "us", None, 5.0)["bin"] is None  # shooter unclear
    few = tracks_of({k: v for k, v in SCENE.items() if k[0] == "us" or k[1] == "8"})
    d = M.defender_distance(few, "us", "7", 5.0)
    assert d["bin"] is None and d["dist_m"] is None  # one tracked defender: the nearest may be off camera


def test_shooter_seen_by_two_tracklets_is_unknown():
    tr = tracks_of({**SCENE, ("us", "7", 99): at(10, 3)})
    assert M.defender_distance(tr, "us", "7", 5.0)["bin"] is None


def test_matchup_time_weighted():
    # them#5 sits on us#7 the whole time; them#8 on us#9 for the first half, then switches onto us#4
    paths = dict(SCENE)
    paths[("them", "8", 12)] = lambda t: (21, 2.5) if t < 5 else (20.5, 12.5)
    paths[("them", None, 13)] = at(10, 7)  # far from everyone: guards nobody
    tr = tracks_of(paths)
    poss = pd.DataFrame([dict(start=0.0, end=10.0, offence="us", side="right")])
    m = M.matchups(tr, poss)
    g7 = m["us"]["7"]
    assert g7["by"][0]["defender"] == "5" and g7["by"][0]["share"] > 0.95
    g9 = m["us"]["9"]
    assert g9["by"][0]["defender"] == "8" and 4.0 < g9["by"][0]["s"] < 6.0
    assert g9["unguarded_s"] > 4.0  # nobody within reach after the switch
    assert m["us"]["4"]["by"][0]["defender"] == "8"
    assert "them" not in m or not m["them"]  # they never had the ball


def test_main_writes_json(tmp_path):
    run = tmp_path / "run"
    review = run / "review_v1"
    review.mkdir(parents=True)
    pd.to_pickle(tracks_of(SCENE), run / "tracks.pkl")
    pd.to_pickle(pd.DataFrame([dict(start=0.0, end=10.0, offence="us", side="right", period=1)]), run / "possessions.pkl")
    trips = [{"schema": 2, "pid": 0, "trip": 1, "t0": 0, "t1": 10, "offence": "us",
              "shot": {"t": 5.0, "shooter": "7", "made": True, "zone": "paint_non_rim", "contested": "contested"}},
             {"schema": 2, "pid": 0, "trip": 2, "t0": 0, "t1": 10, "offence": "us",
              "shot": {"t": 6.0, "shooter": None, "made": False, "zone": "three"}}]
    (review / "coach_part1.json").write_text(json.dumps(trips))
    (run / "shot_proposals.json").write_text(json.dumps({"proposals": [{"t": 5.4, "team": "us"}, {"t": 9.0, "team": "us"}]}))
    M.main(["--run", str(run), "--review", str(review)])
    doc = json.loads((run / "matchups.json").read_text())
    shots = doc["shots"]
    assert [s["source"] for s in shots] == ["review", "review", "proposal"]  # 5.4 s matches the reviewed shot
    assert shots[0]["bin"] == "tight" and shots[0]["reviewer"] == "contested"
    assert shots[1]["bin"] is None and shots[2]["bin"] is None
    b = doc["bins"]["us"]
    assert b["tight"] == {"att": 1, "made": 1, "known": 1} and b["unknown"]["att"] == 1
    assert doc["matchups"]["us"]["7"]["by"][0]["defender"] == "5"


def test_page_tables():
    doc = {"shots": [], "bins": {"us": {"tight": {"att": 4, "made": 1, "known": 4}, "contested": {"att": 2, "made": 1, "known": 2},
                                        "open": {"att": 5, "made": 3, "known": 4}, "unknown": {"att": 3, "made": 0, "known": 1}},
                                 "them": {}},
           "matchups": {"us": {"7": {"total_s": 100.0, "unguarded_s": 10.0, "by": [{"defender": "5", "s": 60.0, "share": 0.6}]}},
                        "them": {"5": {"total_s": 80.0, "unguarded_s": 0.0, "by": [{"defender": "7", "s": 50.0, "share": 0.62}]}}}}
    team = M.tables_html(doc, None, "en")
    assert "#5" in team and "60%" in team and "3/4" in team
    me = M.tables_html(doc, "7", "en")
    assert "#7" in me and "#5" in me
    assert M.tables_html(doc, "30", "en") == ""
    assert "防守" in M.tables_html(doc, None, "zh")


def test_pages_show_load_and_matchup_sections(tmp_path):
    import shutil
    from pathlib import Path

    from hoop_tape_miner import render_html

    folder = tmp_path / "game"
    shutil.copytree(Path(__file__).parent / "fixtures" / "report_min", folder)   # us 4 / 7
    (folder / "run").mkdir()
    (folder / "player-4").mkdir()
    for name in ("README.md", "README.en.md"):
        (folder / "player-4" / name).write_text("# #4\n\nText.\n", encoding="utf8")
    stint = dict(t0=0, t1=300, minutes=5.0, tracked_minutes=4.0, coverage=0.8, low_coverage=False, distance_m=410.0,
                 m_per_tracked_min=102.5, sprints=3, top_speed=6.2, hsd_m=55.0)
    (folder / "run" / "load.json").write_text(json.dumps({"params": {}, "players": {"us#4": {
        "team": "us", "number": "4", "stints": [stint], "total": {**stint, "stints": 1}}}}))
    (folder / "run" / "matchups.json").write_text(json.dumps({"shots": [], "bins": {}, "matchups": {
        "us": {"4": {"total_s": 100.0, "unguarded_s": 10.0, "by": [{"defender": "11", "s": 60.0, "share": 0.6}]}}}}))
    team = render_html.page(folder)
    assert ">Matchups and shot defence</h2>" in team and ">对位与出手防守</h2>" in team
    assert "Running load per stint" not in team  # the load table is a player-page section
    me = render_html.page(folder / "player-4")
    assert ">Running load per stint</h2>" in me and "410" in me and "#11 60%" in me
    import re
    toc = dict((t, int(n)) for n, t in re.findall(r'href="#en-s(\d+)">([^<]+)</a>', me))
    assert toc["Running load per stint"] + 1 == toc["Matchups and shot defence"], toc  # contents: load, then matchups
