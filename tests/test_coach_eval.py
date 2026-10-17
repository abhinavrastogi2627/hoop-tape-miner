"""Coach eval: facts vs the official score flow and box score, insight lint."""
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
