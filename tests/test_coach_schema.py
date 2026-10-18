"""Trip schema v2: validation, v1 migration that keeps information, and the coach-check CLI."""
import json

import pytest

from hoop_tape_miner import coach_schema as S


def v2(**kw):
    t = {"schema": 2, "pid": 1, "trip": 1, "t0": 10.0, "t1": 20.0, "offence": "us", "result": "made2",
         "shot": {"t": 18.0, "shooter": "13", "made": True, "points": 2, "zone": "rim", "type": "layup",
                  "contested": "open"},
         "fts": None, "foul": None, "evidence": {"result": [18.0], "shot": [17.0, 18.0]}, "confidence": "high"}
    t.update(kw)
    return t


def test_validate_accepts_a_clean_trip():
    assert S.validate_trip(v2()) == []


def test_validate_rejects_free_text_result():
    errs = S.validate_trip(v2(result="made2 + FT 1/1 (and-one)"))
    assert any("result" in e for e in errs)


def test_validate_accepts_unclear_trip():
    t = v2(result="unclear", shot=None, evidence={}, confidence="low")
    assert S.validate_trip(t) == []


def test_validate_checks_consistency():
    assert S.validate_trip(v2(shot=dict(v2()["shot"], points=3)))            # made2 but a 3-point shot
    assert S.validate_trip(v2(result="foul_ft", shot=None))                  # foul_ft needs fts
    assert S.validate_trip(v2(result="foul_ft", shot=None, fts={"shooter": "4", "made": 3, "att": 2}))
    assert S.validate_trip(v2(offence="none"))                               # dead ball cannot score
    assert S.validate_trip(v2(shot=dict(v2()["shot"], shooter="13 (likely)")))  # jersey or null
    assert S.validate_trip(v2(evidence={}))                                  # result needs evidence times
    assert S.validate_trip(v2(foul={"t": 1, "by_team": "x", "by": None, "on": None, "type": "reach_in",
                                    "cause": None, "led_to": "side-out"}))
    ok = v2(result="foul_ft", shot=None, fts={"shooter": "4", "made": 1, "att": 2},
            foul={"t": 15.0, "by_team": "them", "by": None, "on": "4", "type": "shooting_on_drive",
                  "cause": "late help", "led_to": "2 FT"},
            evidence={"result": [19.0], "foul": [15.0]})
    assert S.validate_trip(ok) == []


def test_migrate_and_one():
    v1 = {"pid": 7, "trip": 1, "start": 440, "end": 452, "offence": "them", "result": "made2 + FT 1/1 (and-one)",
          "scorer_or_shooter": "25 (likely)", "shot_type": "layup", "shot_zone": "rim", "contested": "contested",
          "foul": {"who": "21", "type": "shooting_on_drive", "cause": "late", "led_to": "1 FT"}, "confidence": "medium"}
    t = S.migrate_v1(v1)
    assert t["schema"] == 2 and t["result"] == "made2" and t["result_v1"] == v1["result"]
    assert t["shot"]["points"] == 2 and t["shot"]["made"] is True and t["shot"]["shooter"] == "25"
    assert t["shooter_note"] == "25 (likely)"
    assert t["fts"] == {"shooter": "25", "made": 1, "att": 1}
    assert (t["t0"], t["t1"]) == (440, 452)
    assert t["foul"]["by_team"] == "us" and t["foul"]["by"] == "21" and t["foul"]["led_to"] == "1 FT"
    assert S.validate_trip(t) == []


@pytest.mark.parametrize("res,off,want,pts", [
    ("FT (1/2)", "them", "foul_ft", 1),
    ("FT (2/2, inferred)", "us", "foul_ft", 2),
    ("foul_no_FT", "us", "foul_side", 0),
    ("dead_ball_timeout", "none (dead ball)", "dead_ball", 0),
    ("missed (post shot left block ~253s)", "us", "missed", 0),
    ("made3", "us", "made3", 3),
    ("turnover", "them", "turnover", 0),
    ("end_period", "us", "end_period", 0),
    ("unclear (continues into P16)", "us", "unclear", None),
    ("something odd", "us", "unclear", None),
    (None, "us", "unclear", None),
])
def test_migrate_results(res, off, want, pts):
    from hoop_tape_miner.coach_eval import trip_points
    t = S.migrate_v1({"pid": 1, "t_start": 5, "t_end": 9, "offence": off, "result": res,
                      "scorer_or_shooter": None, "confidence": "low"})
    assert t["result"] == want and t["result_v1"] == res
    assert trip_points(t) == pts
    assert S.validate_trip(t) == [], S.validate_trip(t)
    if want == "missed":
        assert t["shot"]["made"] is False and "left block" in t["result_note"]
    if want == "dead_ball":
        assert t["offence"] == "none"
    if want == "unclear" and res:
        assert t["result_note"] or t["result_v1"] == res


def test_migrate_keeps_unknown_enum_values_and_nested_defence():
    v1 = {"pid": 1, "t0": 1, "t1": 4, "offence": "them", "result": "foul_no_FT", "confidence": "sure",
          "defence": {"scheme": "man", "foul": {"who": "us (prob #17)", "type": "hand_check",
                                                "led_to": "1 FT (and-1, looks missed) - unclear"}}}
    t = S.migrate_v1(v1)
    assert t["scheme"] == "man" and "defence" not in t
    assert t["foul"]["by_team"] == "us" and t["foul"]["by"] is None
    assert t["foul"]["by_note"] == "us (prob #17)"
    assert t["foul"]["type"] == "unclear" and t["foul"]["type_v1"] == "hand_check"
    assert t["foul"]["led_to"] == "1 FT" and t["foul"]["led_to_v1"].startswith("1 FT (and-1")
    assert t["confidence"] == "low" and t["confidence_v1"] == "sure"
    assert S.validate_trip(t) == []


def test_migrate_is_idempotent_on_v2():
    t = v2()
    assert S.migrate_v1(t) == t


def write_review(d, trips, part=1):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"coach_part{part}.json").write_text(json.dumps(trips), encoding="utf8")
    (d / f"part{part}.json").write_text(json.dumps([{"pid": 1, "start": 5, "end": 9}]), encoding="utf8")
    (d / "manifest.json").write_text("{}", encoding="utf8")


def test_validate_part_reports_bad_json(tmp_path):
    p = tmp_path / "coach_part1.json"
    p.write_text("[{", encoding="utf8")
    assert S.validate_part(p)
    p.write_text(json.dumps([v2()]), encoding="utf8")
    assert S.validate_part(p) == []
    p.write_text(json.dumps([{"pid": 1, "result": "made2"}]), encoding="utf8")
    errs = S.validate_part(p)
    assert errs and all(e.startswith("coach_part1.json") for e in errs)


def test_coach_check_cli_and_migrate(tmp_path, capsys):
    src, out = tmp_path / "review_v1", tmp_path / "review_v2m"
    write_review(src, [{"pid": 1, "offence": "us", "result": "made2 + FT 1/1 (and-one)", "scorer_or_shooter": "4"}])
    with pytest.raises(SystemExit) as e:
        S.main(["--review", str(src)])
    assert e.value.code == 1 and "result" in capsys.readouterr().out
    S.main(["--review", str(src), "--migrate", str(out)])
    trips = json.loads((out / "coach_part1.json").read_text(encoding="utf8"))
    assert trips[0]["result"] == "made2" and (trips[0]["t0"], trips[0]["t1"]) == (5, 9)  # times from part1.json
    assert (out / "part1.json").exists() and (out / "manifest.json").exists()
    S.main(["--review", str(out)])
    assert "ok" in capsys.readouterr().out.lower()
