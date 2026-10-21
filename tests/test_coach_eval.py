"""Coach eval: facts vs the official score flow and box score, insight lint, part coverage, the eval gate."""
import json

import pytest

from hoop_tape_miner import coach_eval as E
from hoop_tape_miner.coach_eval import facts_eval, insight_lint, jersey, trip_points, trip_times


def official(flow, players=None):
    return {"score_flow": flow, "players": players or {"us": {}, "them": {}}}


def ev(t, team, pts):
    return {"our_video_t": t, "team": team, "points": pts}


def test_trip_parsing_v1_variants():
    assert trip_times({"t0": 10, "t1": 20}) == (10, 20)
    assert trip_times({"start": 5, "end": 9}) == (5, 9)
    assert trip_times({"t_start": 1, "t_end": 2}) == (1, 2)
    assert trip_points({"result": "made2 + FT 1/1 (and-one)"}) == 3
    assert trip_points({"result": "FT (2/2, inferred)"}) == 2
    assert trip_points({"result": "made3"}) == 3
    assert trip_points({"result": "missed (post shot)"}) == 0
    assert trip_points({"result": "unclear"}) is None
    assert jersey("25 (likely, the stealer)") == "25"
    assert jersey("#17") == "17"
    assert jersey("45 or 13 (unclear)") is None
    assert jersey("unclear (possibly #19)") is None
    assert jersey(None) is None


def test_facts_eval_matches_lagged_events():
    trips = [{"offence": "us", "t0": 70, "t1": 80, "result": "made2", "scorer_or_shooter": "13"}]
    r = facts_eval(trips, official([ev(100, "us", 2)], {"us": {"13": {"PTS": 2, "PF": 0}}, "them": {}}))
    assert r["us"]["pts_recall"] == 1.0 and r["us"]["pts_precision"] == 1.0
    assert r["us"]["team_pts"] == [2, 2]
    assert r["us"]["player_pts_abs_err"] == 0 and r["us"]["unattributed_pts"] == 0


def test_facts_eval_and_one_consumes_two_events():
    trips = [{"offence": "them", "t0": 440, "t1": 452, "result": "made2 + FT 1/1 (and-one)"}]
    r = facts_eval(trips, official([ev(470, "them", 2), ev(480, "them", 1)]))
    assert r["them"]["pts_recall"] == 1.0
    assert r["them"]["unattributed_pts"] == 3


def test_facts_eval_unclear_is_not_a_miss():
    trips = [{"offence": "us", "t0": 0, "t1": 10, "result": "unclear"},
             {"offence": "us", "t0": 10, "t1": 20, "result": "missed"}]
    r = facts_eval(trips, official([]))
    assert r["us"]["trips"] == 2 and r["us"]["unclear"] == 1 and r["us"]["missed"] == 1


def test_facts_eval_boundary_and_window():
    # two trips from different parts; the event at 300 belongs to the trip that ended at 290, not the one at 200
    trips = [{"offence": "us", "t0": 190, "t1": 200, "result": "made2"},
             {"offence": "us", "t0": 280, "t1": 290, "result": "made2"}]
    r = facts_eval(trips, official([ev(300, "us", 2)]))
    assert r["us"]["pts_recall"] == 1.0 and r["us"]["pts_precision"] == 0.5


def test_facts_eval_fouls_and_invalid_results():
    trips = [{"offence": "them", "t0": 0, "t1": 9, "result": "foul_no_FT", "foul": {"who": "us (prob #17)"}},
             {"offence": "them", "t0": 9, "t1": 19, "result": "FT (1/2)", "foul": {"who": "21"}},
             {"offence": "none (dead ball)", "t0": 19, "t1": 29, "result": "dead_ball_timeout"}]
    players = {"us": {"17": {"PTS": 0, "PF": 1}, "21": {"PTS": 0, "PF": 2}}, "them": {}}
    r = facts_eval(trips, official([], players))
    assert r["us"]["fouls_found"] == 2 and r["us"]["fouls_official"] == 3
    assert r["us"]["player_pf_abs_err"] == 1 + 1  # #17 unattributed (prob) -> 1 missing; #21 1 of 2
    assert r["invalid_result_share"] == round(1 / 3, 3)


def test_insight_lint_text_items():
    items = ["对手顶人时安排第二个持球人。",
             "P18 07:28 和 P24 10:23 两次被断，因为没人接应；练 3 分钟 2v1 推进，下场目标失误 ≤3 次。",
             "加强沟通，提高专注。"]
    r = insight_lint(items)
    assert r["n"] == 3 and r["with_evidence"] == 1 and r["with_why"] == 1
    assert r["with_drill"] == 1 and r["with_target"] == 1 and r["generic_phrases"] == 2


def test_insight_lint_dicts():
    ins = [{"claim": "x", "why": "y", "evidence": [{"t": 1}, {"t": 2}], "drill": "2v1", "target_next_game": "≤3"},
           {"claim": "x", "why": "", "evidence": [{"t": 1}], "drill": "", "target_next_game": ""}]
    r = insight_lint(ins)
    assert (r["n"], r["with_evidence"], r["with_why"], r["with_drill"], r["with_target"]) == (2, 1, 1, 1, 1)


def test_facts_eval_skips_events_outside_the_video():
    trips = [{"offence": "us", "t0": 70, "t1": 80, "result": "made2"}]
    r = facts_eval(trips, official([ev(100, "us", 2), {"our_video_t": None, "team": "us", "points": 1}]))
    assert r["us"]["pts_recall"] == 1.0 and r["us"]["official_pts_off_video"] == 1


def test_off_roster_jerseys_count_as_errors_and_evidence_needs_two_times():
    trips = [{"offence": "us", "t0": 70, "t1": 80, "result": "made2", "scorer_or_shooter": "45"}]
    r = facts_eval(trips, official([ev(100, "us", 2)], {"us": {"13": {"PTS": 2, "PF": 0}}, "them": {}}))
    assert r["us"]["player_pts_abs_err"] == 4 and r["us"]["unknown_jerseys"] == ["45"]
    assert insight_lint(["P18 07:28 lost the ball"])["with_evidence"] == 0
    assert insight_lint(["07:28 and 10:23 lost the ball"])["with_evidence"] == 1


def v2trip(**kw):
    t = {"schema": 2, "offence": "us", "t0": 150, "t1": 200, "result": "made2", "fts": None, "foul": None,
         "shot": {"t": 80, "shooter": "13", "made": True, "points": 2}}
    t.update(kw)
    return t


def test_eval_reads_v2_fields():
    ft = v2trip(result="foul_ft", shot=None, t0=300, t1=310, fts={"shooter": "4", "made": 2, "att": 2},
                foul={"t": 305, "by_team": "them", "by": "9", "type": "shooting_on_drive"})
    assert trip_points(ft) == 2 and trip_points(v2trip()) == 2
    assert trip_points(v2trip(result="unclear", shot=None)) is None
    players = {"us": {"13": {"PTS": 2, "PF": 0}, "4": {"PTS": 2, "PF": 0}}, "them": {"9": {"PTS": 0, "PF": 1}}}
    r = facts_eval([v2trip(), ft], official([ev(100, "us", 2), ev(320, "us", 1), ev(321, "us", 1)], players))
    assert r["us"]["pts_recall"] == 1.0  # shot.t = 80 is inside the lag window of the event at 100; t1 = 200 is not
    assert r["us"]["player_pts_abs_err"] == 0 and r["us"]["unattributed_pts"] == 0
    assert r["them"]["fouls_found"] == 1 and r["them"]["player_pf_abs_err"] == 0
    assert r["invalid_result_share"] == 1.0  # v2 trips go through validate_trip: these lack evidence/confidence


def test_eval_event_level():
    and_one = v2trip(shot={"t": 80, "shooter": "13", "made": True, "points": 2},
                     fts={"shooter": "13", "made": 1, "att": 1})
    three_as_two = v2trip(t0=380, t1=400, shot={"t": 390, "shooter": "13", "made": True, "points": 2})
    flow = [ev(100, "us", 2), ev(105, "us", 1), ev(400, "us", 3), ev(600, "us", 2), ev(610, "us", 1)]
    r = facts_eval([and_one, three_as_two], official(flow))
    assert r["us"]["events"] == {"shots": 3, "fts": 2}
    assert r["us"]["events_matched"] == {"shots": 2, "fts": 1}
    assert r["us"]["shot_points_agree"] == 1  # the 3 recorded as a 2 is found but its value disagrees


# ---- honest gates: part coverage, unresolved jerseys, the eval gate and regressions ----

def write_part(review, n, poss, trips):
    review.mkdir(parents=True, exist_ok=True)
    (review / f"part{n}.json").write_text(json.dumps([{"pid": p, "start": a, "end": b, "sheets": []}
                                                      for p, a, b in poss]), encoding="utf8")
    if trips is not None:
        (review / f"coach_part{n}.json").write_text(json.dumps(trips), encoding="utf8")


def trip(pid, t0, t1, n=1, **kw):
    t = {"schema": 2, "pid": pid, "trip": n, "t0": t0, "t1": t1, "offence": "us", "result": "unclear",
         "shot": None, "fts": None, "foul": None}
    t.update(kw)
    return t


def test_coverage_passes_when_every_pid_is_covered(tmp_path):
    write_part(tmp_path, 1, [(1, 10, 30), (2, 30, 60)], [trip(1, 10, 30), trip(2, 30, 45), trip(2, 45, 60, 2)])
    assert E.part_coverage(tmp_path) == []


def test_coverage_lists_missing_pids_and_gaps(tmp_path):
    write_part(tmp_path, 1, [(1, 10, 30), (2, 30, 90), (3, 90, 100)], [trip(1, 10, 30), trip(2, 30, 40)])
    errs = E.part_coverage(tmp_path)
    assert any("pid 3" in e and "no trip" in e for e in errs)
    gap = [e for e in errs if "pid 2" in e and "gap" in e]
    assert gap and "00:40-01:30" in gap[0] and "50.0 s" in gap[0]
    # a short uncovered stretch (below the rule) is fine
    write_part(tmp_path, 1, [(1, 10, 30)], [trip(1, 10, 25)])
    assert E.part_coverage(tmp_path) == []


def test_coverage_missing_coach_part_and_string_pids(tmp_path):
    write_part(tmp_path, 1, [(5, 0, 20)], None)
    assert any("coach_part1.json" in e and "missing" in e for e in E.part_coverage(tmp_path))
    write_part(tmp_path, 1, [(5, 0, 20)], [trip("5", 0, 20)])
    assert E.part_coverage(tmp_path) == []


def test_unresolved_jerseys_need_a_note(tmp_path):
    made = trip(1, 0, 20, result="made2", shot={"t": 5, "shooter": None, "made": True, "points": 2})
    write_part(tmp_path, 1, [(1, 0, 20)], [made])
    errs = E.part_coverage(tmp_path)
    assert any("shot.shooter" in e and "unknown" in e for e in errs)
    made["shooter_note"] = "unknown: back to camera"
    write_part(tmp_path, 1, [(1, 0, 20)], [made])
    assert E.part_coverage(tmp_path) == []
    foul = trip(1, 0, 20, result="foul_side", foul={"t": 4, "by_team": "us", "by": None, "type": "reach_in"})
    ft = trip(1, 0, 20, 2, result="foul_ft", fts={"shooter": None, "made": 1, "att": 2})
    write_part(tmp_path, 1, [(1, 0, 20)], [foul, ft])
    errs = E.part_coverage(tmp_path)
    assert any("foul.by" in e for e in errs) and any("fts.shooter" in e for e in errs)
    foul["foul"]["by_note"] = "unknown"
    ft["fts"]["shooter_note"] = "unknown"
    write_part(tmp_path, 1, [(1, 0, 20)], [foul, ft])
    assert E.part_coverage(tmp_path) == []


def test_coach_check_cli_fails_on_coverage(tmp_path, capsys):
    from hoop_tape_miner import coach_schema
    ok = trip(1, 0, 20, confidence="low")
    write_part(tmp_path, 1, [(1, 0, 20), (2, 20, 40)], [ok])
    with pytest.raises(SystemExit):
        coach_schema.main(["--review", str(tmp_path)])
    assert "pid 2" in capsys.readouterr().out
    write_part(tmp_path, 1, [(1, 0, 20), (2, 20, 40)], [ok, trip(2, 20, 40, confidence="low")])
    coach_schema.main(["--review", str(tmp_path)])
    assert "ok" in capsys.readouterr().out


def facts(us_recall=1.0, us_prec=1.0, them_recall=1.0, them_prec=1.0, pts_err=0, invalid=0.0):
    def side(r, p):
        return {"pts_recall": r, "pts_precision": p, "player_pts_abs_err": pts_err, "player_pf_abs_err": 0}
    return {"us": side(us_recall, us_prec), "them": side(them_recall, them_prec), "invalid_result_share": invalid}


def test_gate_blocks_low_recall_and_skips_what_it_cannot_compute():
    g = E.gate(facts())
    assert g["pass"] and not g["failed"]
    g = E.gate(facts(them_recall=0.5))
    assert not g["pass"] and any("them pts_recall" in f for f in g["failed"])
    g = E.gate(facts(us_recall=None, us_prec=None))
    assert g["pass"] and any("us pts_recall" in s for s in g["skipped"])


def test_regressions_against_the_previous_entry():
    prev, cur = facts(), facts(us_recall=0.9, pts_err=4)
    w = E.regressions(prev, cur)
    assert any("us pts_recall" in x and "1.0" in x and "0.9" in x for x in w)
    assert any("player_pts_abs_err" in x for x in w)
    assert E.regressions(cur, prev) == [] and E.regressions(None, cur) == []


def eval_review(tmp_path):
    r = tmp_path / "review"
    write_part(r, 1, [(1, 80, 120)], [trip(1, 80, 120, result="made2", confidence="low",
                                           evidence={"result": [90], "shot": [90]},
                                           shot={"t": 90, "shooter": "13", "made": True, "points": 2})])
    off = tmp_path / "official.json"
    flow = [{"our_video_t": 100, "team": "us", "points": 2}, {"our_video_t": 300, "team": "them", "points": 2}]
    off.write_text(json.dumps({"score_flow": flow, "players": {"us": {"13": {"PTS": 2}}, "them": {}}}),
                   encoding="utf8")
    return r, off


def test_main_gate_records_result_and_exits_1(tmp_path, capsys):
    r, off = eval_review(tmp_path)
    with pytest.raises(SystemExit) as e:
        E.main(["--review", str(r), "--official", str(off), "--label", "run", "--gate"])
    assert e.value.code not in (0, None)
    res = json.loads((r / "eval" / "run.json").read_text(encoding="utf8"))
    assert res["gate"]["pass"] is False and any("them pts_recall" in f for f in res["gate"]["failed"])
    assert "gate FAIL" in (r / "eval" / "log.md").read_text(encoding="utf8")
    # without --gate the same numbers are recorded and the exit is 0
    E.main(["--review", str(r), "--official", str(off), "--label", "manual"])
    assert "our rule" in capsys.readouterr().out


def test_main_warns_on_regression(tmp_path, capsys):
    r, off = eval_review(tmp_path)
    (r / "eval").mkdir()
    old = {"label": "old", "at": "2000-01-01T00:00:00", "facts": facts()}
    (r / "eval" / "old.json").write_text(json.dumps(old), encoding="utf8")
    (r / "eval" / "ab.key.json").write_text("{}", encoding="utf8")  # files without facts are ignored
    E.main(["--review", str(r), "--official", str(off), "--label", "new"])
    out = capsys.readouterr().out
    assert "WARNING" in out and "them pts_recall" in out
    res = json.loads((r / "eval" / "new.json").read_text(encoding="utf8"))
    assert res["previous"] == "old" and res["regressions"]
