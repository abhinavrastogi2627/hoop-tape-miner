"""Four Factors and points per trip type from reviewed v2 trips (+ the official box score), the optional trip fields
`transition` / `turnover_kind` and the coach-insights number check on them."""
import json

from hoop_tape_miner import coach_schema as S
from hoop_tape_miner import coach_summary as CS
from hoop_tape_miner import official
from hoop_tape_miner.coach_insights import validate_insights


def trip(t0, off, result, entry=None, shot_t=None, pts=None, made=None, fts=None, t1=None, **kw):
    """Synthetic v2 trip; a shot object is added for made2/made3/missed."""
    x = {"schema": 2, "pid": int(t0), "trip": 1, "t0": t0, "t1": t1 if t1 is not None else t0 + 8, "offence": off,
         "result": result, "entry": entry, "shot": None, "fts": fts, "foul": None, "confidence": "high"}
    if result in ("made2", "made3", "missed"):
        x["shot"] = {"t": shot_t, "shooter": None, "made": result != "missed",
                     "points": int(result[-1]) if result != "missed" else (pts or 2), "zone": None, "type": None,
                     "contested": None}
    x.update(kw)
    return x


# us 8 trips (1 second chance -> 7 possessions), them 6 trips (6 possessions)
TRIPS = [
    trip(0, "us", "made2", "halfcourt_set", 15),                       # us half-court 2
    trip(20, "them", "made3", "transition", 24),                       # them transition 3
    trip(30, "us", "missed", "halfcourt_set", 45),                     # us miss ...
    trip(47, "us", "made2", None, 48),                                 # ... offensive rebound: second chance 2
    trip(55, "them", "missed", "halfcourt_set", 70),                   # them miss, we rebound
    trip(72, "us", "made2", None, 76),                                 # no entry: 4 s to the shot -> transition 2
    trip(80, "them", "turnover", "halfcourt_set", turnover_kind="live"),
    trip(82, "us", "foul_ft", None, transition=True, fts={"shooter": None, "made": 1, "att": 2}),  # after live TO, 1
    trip(90, "them", "turnover", "halfcourt_set", turnover_cause="out_of_bounds"),  # dead (from the cause)
    trip(95, "us", "turnover", "halfcourt_set", turnover_cause="steal_on_ball"),    # live (from the cause)
    trip(100, "them", "made2", "early_offense", 103),                  # transition after our live TO, 2
    trip(110, "us", "unclear", None, t1=None),                         # no entry, no time -> unknown
    trip(120, "them", "missed", "halfcourt_set", 135),                 # them miss, we rebound
    trip(140, "us", "end_period", None),                               # unknown, 0
]


def test_schema_accepts_the_optional_fields_and_old_trips():
    base = TRIPS[0]
    assert S.validate_trip(dict(base, evidence={"result": [15.0], "shot": [15.0]})) == []
    ok = dict(base, transition=False, evidence={"result": [15.0], "shot": [15.0]})
    assert S.validate_trip(ok) == []
    to = dict(TRIPS[6], turnover_kind="dead", transition=None, evidence={"result": [81.0]})
    assert S.validate_trip(to) == []


def test_schema_rejects_bad_optional_fields():
    ev = {"evidence": {"result": [81.0]}}
    assert any("transition" in e for e in S.validate_trip(dict(TRIPS[6], transition="yes", **ev)))
    assert any("turnover_kind" in e for e in S.validate_trip(dict(TRIPS[6], turnover_kind="stolen", **ev)))
    made = dict(TRIPS[0], turnover_kind="live", evidence={"result": [15.0], "shot": [15.0]})
    assert any("turnover_kind" in e for e in S.validate_trip(made))


def test_official_recorded_flags():
    makes_only = {"totals": {"us": {"FGM-A": {"made": 4, "att": 4}, "FTM-A": {"made": 3, "att": 3}},
                             "them": {"FGM-A": {"made": 2, "att": 2}, "FTM-A": {"made": 0, "att": 0}}}}
    assert official.recorded(makes_only) == {"attempts": False, "turnovers": False, "rebounds": False}
    full = {"totals": {"us": {"FGM-A": {"made": 4, "att": 9}, "TOV": 3, "ORB": 2},
                       "them": {"FGM-A": {"made": 5, "att": 10}, "TOV": 4, "ORB": 1}}}
    assert official.recorded(full) == {"attempts": True, "turnovers": True, "rebounds": True}


def test_official_parses_turnovers_and_offensive_rebounds_when_the_sheet_has_them():
    st = [{"shortName": "TO", "value": "5"}, {"shortName": "OREB", "value": "3"}, {"shortName": "PTS", "value": "9"}]
    assert official._stats(st) == {"TOV": 5, "ORB": 3, "PTS": 9}


def test_four_factors_from_review_only():
    ff = CS.four_factors(CS.annotate(TRIPS), min_poss=1)
    us, them = ff["us"], ff["them"]
    assert us["possessions"] == 7 and them["possessions"] == 6
    assert us["possessions_source"] == them["possessions_source"] == "review trips"
    assert (us["fgm"], us["fg3m"], us["fga"], us["ftm"], us["fta"]) == (3, 0, 4, 1, 2)
    assert us["efg_pct"] == 75.0 and them["efg_pct"] == 62.5
    assert us["ft_rate_pct"] == 25.0 and them["ft_rate_pct"] == 0.0
    assert (us["tov"], us["tov_live"], us["tov_dead"], us["tov_unknown"]) == (1, 1, 0, 0)
    assert (them["tov"], them["tov_live"], them["tov_dead"]) == (2, 1, 1)
    assert us["tov_pct"] == 14.3 and them["tov_pct"] == 33.3
    assert us["tov_live_pct"] == 14.3 and them["tov_dead_pct"] == 16.7
    assert (us["orb"], us["orb_chances"], us["orb_pct"]) == (1, 1, 100.0)
    assert (them["orb"], them["orb_chances"], them["orb_pct"]) == (0, 2, 0.0)
    assert us["points"] == 7 and them["points"] == 5
    assert us["ppp"] == 1.0 and them["ppp"] == 0.83
    d = ff["decided"]
    # weighted gaps (pp, + = favours us): eFG 0.4*12.5=5.0, TOV 0.25*19.0=4.75, ORB 0.2*100=20, FT 0.15*25=3.75
    assert d["status"] == "ok" and d["factor"] == "orb" and d["favours"] == "us"
    assert d["weighted"]["orb"] == 20.0 and d["weighted"]["efg"] == 5.0
    assert "offensive rebounding" in d["text"] and "100.0" in d["text"]


def test_decided_is_unclear_on_tiny_samples():
    d = CS.four_factors(CS.annotate(TRIPS))["decided"]
    assert d["status"] == "unclear" and d["factor"] is None
    assert "unclear" in d["text"] and "7" in d["text"]


def test_ppp_by_trip_type():
    p = CS.ppp(CS.annotate(TRIPS))
    us, them = p["us"], p["them"]
    assert us["half_court"] == {"trips": 3, "points": 2, "ppp": 0.67}
    assert us["second_chance"] == {"trips": 1, "points": 2, "ppp": 2.0}
    assert us["transition"] == {"trips": 2, "points": 3, "ppp": 1.5}
    assert us["unknown"] == {"trips": 2, "points": 0, "ppp": 0.0}
    assert us["after_live_turnover"] == {"trips": 1, "points": 1, "ppp": 1.0}
    assert them["transition"] == {"trips": 2, "points": 5, "ppp": 2.5}
    assert them["half_court"] == {"trips": 4, "points": 0, "ppp": 0.0}
    assert them["second_chance"] == {"trips": 0, "points": 0, "ppp": None}
    assert them["after_live_turnover"] == {"trips": 1, "points": 2, "ppp": 2.0}


def test_transition_time_rule_needs_a_time():
    late = trip(0, "us", "made2", None, 12)  # 12 s to the shot: half-court by our rule
    none = trip(0, "us", "made2", None, None)
    assert CS.annotate([late])[0]["_kind"] == "half_court"
    assert CS.annotate([none])[0]["_kind"] == "unknown"
    assert CS.annotate([trip(0, "us", "made2", "transition", 12, transition=False)])[0]["_kind"] == "half_court"


OFF_MAKES = {"totals": {"us": {"PTS": 10, "FGM-A": {"made": 4, "att": 4}, "3PM-A": {"made": 1, "att": 1},
                               "FTM-A": {"made": 1, "att": 1}},
                        "them": {"PTS": 5, "FGM-A": {"made": 2, "att": 2}, "3PM-A": {"made": 1, "att": 1},
                                 "FTM-A": {"made": 0, "att": 0}}}}


def test_official_makes_plus_reviewed_misses():
    ff = CS.four_factors(CS.annotate(TRIPS), OFF_MAKES, min_poss=1)
    us = ff["us"]
    # official makes (4 FG, 1 three) + 1 reviewed miss; FTM official 1, FTA reviewed 2
    assert (us["fgm"], us["fg3m"], us["fga"], us["ftm"], us["fta"]) == (4, 1, 5, 1, 2)
    assert us["efg_pct"] == 90.0 and us["ft_rate_pct"] == 20.0
    assert us["sources"]["shooting"] == "official makes + reviewed misses"
    assert us["points_official"] == 10 and us["points"] == 7
    assert ff["method"]["ft_rate"].startswith("FTM / FGA")


def test_unobserved_official_free_throws_raise_attempts_to_at_least_makes():
    off = json.loads(json.dumps(OFF_MAKES))
    off["totals"]["us"]["FTM-A"] = {"made": 3, "att": 3}
    us = CS.four_factors(CS.annotate(TRIPS), off, min_poss=1)["us"]
    assert (us["ftm"], us["fta"]) == (3, 4)  # 2 reviewed attempts (1 made) + 2 made the review missed


def test_official_attempts_used_when_recorded_and_formula_when_no_trips():
    off = {"totals": {s: {"PTS": 20, "FGM-A": {"made": 8, "att": 20}, "3PM-A": {"made": 2, "att": 6},
                          "FTM-A": {"made": 2, "att": 5}, "TOV": 6, "ORB": 4} for s in ("us", "them")}}
    ff = CS.four_factors([], off, min_poss=1)
    us = ff["us"]
    assert (us["fga"], us["fta"]) == (20, 5)
    assert us["possessions"] == 24.2 and us["possessions_source"] == "estimate FGA - ORB + TOV + 0.44*FTA"
    assert us["efg_pct"] == 45.0 and us["tov_pct"] == 24.8
    assert us["orb_pct"] is None  # no defensive rebounds known for the other side
    assert ff["decided"]["status"] == "unclear"


def test_summarise_has_four_factors_and_ppp(tmp_path, capsys):
    review = tmp_path / "review"
    review.mkdir()
    (review / "coach_part1.json").write_text(json.dumps(TRIPS), encoding="utf8")
    off = tmp_path / "official.json"
    off.write_text(json.dumps(OFF_MAKES), encoding="utf8")
    out = tmp_path / "summary.json"
    CS.main(["--review", str(review), "--official", str(off), "--segments", "A:0-60", "--out", str(out)])
    s = json.loads(out.read_text(encoding="utf8"))
    assert s["all"]["four_factors"]["us"]["fga"] == 5          # official merged for the whole game
    assert s["A"]["four_factors"]["us"]["fga"] == 3            # stretches: review only (2 made + 1 miss)
    assert s["A"]["four_factors"]["us"]["sources"]["shooting"] == "review"
    assert s["all"]["ppp"]["us"]["second_chance"]["trips"] == 1
    assert s["A"]["ppp"]["us"]["second_chance"]["trips"] == 1  # context from the whole game, not the slice
    assert s["all"]["us"]["trips"] == 8                        # old keys unchanged


def test_insights_check_verifies_four_factors_numbers():
    summary = {"all": {"four_factors": CS.four_factors(CS.annotate(TRIPS), min_poss=1)}}
    ins = [{"id": "x", "claim": "c", "why": "w", "rule": "r", "drill": "d", "target_next_game": "t",
            "evidence": [{"t": 1.0, "pid": 0, "trip": 1}, {"t": 21.0, "pid": 20, "trip": 1}], "kb": ["k"], "confidence": "high",
            "critic": {"verdict": "keep"}, "numbers": {"all.four_factors.us.efg_pct": 70.0,
                                                        "all.four_factors.them.tov_pct": 33.3}}]
    errs = validate_insights(ins, TRIPS, None, summary)
    assert errs == ["insight x: number all.four_factors.us.efg_pct = 70.0 but summary.json says 75.0"]


def test_rebound_field_wins_over_the_next_trip_and_putback_after_free_throws():
    miss = trip(0, "us", "missed", "halfcourt_set", 5, oreb_crash={"n": 1, "rebound": "them"})
    again = trip(10, "us", "made2", "halfcourt_set", 14)  # they rebounded and lost it: a new possession of ours
    ft = trip(20, "us", "foul_ft", "halfcourt_set", fts={"shooter": None, "made": 1, "att": 2})
    put = trip(25, "us", "made2", "OREB_putback", 26)      # rebound of the missed free throw
    xs = CS.annotate([miss, again, ft, put])
    assert [x["_kind"] for x in xs] == ["half_court", "half_court", "half_court", "second_chance"]
    us = CS.four_factors(xs, min_poss=1)["us"]
    assert (us["orb"], us["orb_chances"], us["possessions"]) == (0, 1, 3)
