"""Coach insights: validation against trips, KB and summary; blind A/B sheet."""
import json
import re

import pytest

from hoop_tape_miner.coach_insights import build_ab, kb_slugs, main, validate_insights

TRIPS = [{"schema": 2, "pid": 1, "trip": 1, "t0": 100.0, "t1": 110.0, "offence": "them"},
         {"schema": 2, "pid": 4, "trip": 1, "t0": 300.0, "t1": 312.0, "offence": "them"}]
SUMMARY = {"all": {"us": {"turnovers": 9}, "them": {"transition_scores": 6}}}
KB = {"transition-defence", "foul-discipline"}


def insight(**kw):
    base = {"id": "T1", "player": None, "kb": ["transition-defence"],
            "claim": "Their fast breaks came after our missed shots with two of us crashing.",
            "why": "Two crashers and a guard who stops to argue leave nobody between ball and rim.",
            "evidence": [{"t": 104.0, "pid": 1, "trip": 1, "what": "two crash, nobody back"},
                         {"t": 305.5, "pid": 4, "trip": 1, "what": "outlet over the top"}],
            "counter_examples": [], "numbers": {"all.them.transition_scores": 6},
            "rule": "Shot goes up: the guard sprints back to the paint.",
            "drill": "3-on-2 to 2-on-1, 10 reps, guard back first every rep.",
            "target_next_game": "transition scores against at most 3",
            "confidence": "medium", "critic": {"verdict": "keep", "note": "both checked"}}
    base.update(kw)
    return base


def test_valid_insight_passes():
    assert validate_insights([insight()], TRIPS, KB, SUMMARY) == []


def test_insight_needs_two_evidence_times():
    one = insight(evidence=[{"t": 104.0, "pid": 1, "trip": 1, "what": "x"}])
    errs = validate_insights([one], TRIPS, KB, SUMMARY)
    assert any("evidence" in e for e in errs)
    same = insight(evidence=[{"t": 104.0, "pid": 1, "trip": 1, "what": "x"}] * 2)
    assert validate_insights([same], TRIPS, KB, SUMMARY)


def test_insight_orphan_time_fails():
    bad = insight(evidence=[{"t": 104.0, "pid": 1, "trip": 1, "what": "x"},
                            {"t": 200.0, "pid": 2, "trip": 1, "what": "between trips"}])
    errs = validate_insights([bad], TRIPS, KB, SUMMARY)
    assert any("200" in e and "no trip" in e for e in errs)
    slack = insight(evidence=[{"t": 104.0, "what": "x"}, {"t": 112.5, "what": "just after the trip, within 3 s"}])
    assert validate_insights([slack], TRIPS, KB, SUMMARY) == []
    counter = insight(counter_examples=[{"t": 500.0, "what": "orphan counter-example"}])
    assert validate_insights([counter], TRIPS, KB, SUMMARY)


def test_unknown_kb_slug_fails():
    errs = validate_insights([insight(kb=["zone-offence"])], TRIPS, KB, SUMMARY)
    assert any("zone-offence" in e for e in errs)
    assert validate_insights([insight(kb=[])], TRIPS, KB, SUMMARY)


def test_number_mismatch_fails():
    errs = validate_insights([insight(numbers={"all.us.turnovers": 7})], TRIPS, KB, SUMMARY)
    assert any("all.us.turnovers" in e for e in errs)
    assert validate_insights([insight(numbers={"all.us.turnovers": 9})], TRIPS, KB, SUMMARY) == []
    # a name the summary does not have is not checked here (e.g. a features or official number)
    assert validate_insights([insight(numbers={"features.p1.numbers_back_2s": 1})], TRIPS, KB, SUMMARY) == []


def test_dropped_insight_fails():
    errs = validate_insights([insight(critic={"verdict": "drop", "note": "not on film"})], TRIPS, KB, SUMMARY)
    assert any("drop" in e for e in errs)
    assert validate_insights([insight(critic=None)], TRIPS, KB, SUMMARY)
    assert validate_insights([insight(rule="")], TRIPS, KB, SUMMARY)
    assert validate_insights([], TRIPS, KB, SUMMARY)


def test_kb_slugs_parses_headings(tmp_path):
    p = tmp_path / "kb.md"
    p.write_text("# KB\n\n### KB-transition-defence\ntext\n\n### KB-foul-discipline\n", encoding="utf8")
    assert kb_slugs(p) == {"transition-defence", "foul-discipline"}


def test_check_cli_exits_1_on_errors(tmp_path):
    (tmp_path / "coach_part1.json").write_text(json.dumps(TRIPS), encoding="utf8")
    (tmp_path / "summary.json").write_text(json.dumps(SUMMARY), encoding="utf8")
    kb = tmp_path / "kb.md"
    kb.write_text("### KB-transition-defence\n", encoding="utf8")
    (tmp_path / "insights.json").write_text(json.dumps([insight()]), encoding="utf8")
    assert main(["check", "--review", str(tmp_path), "--kb", str(kb)]) == 0
    (tmp_path / "insights.json").write_text(json.dumps([insight(kb=["nope"])]), encoding="utf8")
    with pytest.raises(SystemExit) as e:
        main(["check", "--review", str(tmp_path), "--kb", str(kb)])
    assert e.value.code not in (0, None)


def test_ab_sheet_is_blind(tmp_path):
    memo = "# Memo\n\n## The 3 most important coaching conclusions\n1. **Box out** after every shot (05:12).\n" \
           "2. Get back on defence, 3 trips gave up layups.\n3. Stop reaching from behind.\n"
    (tmp_path / "memo_part1.md").write_text(memo, encoding="utf8")
    (tmp_path / "insights.json").write_text(json.dumps([insight(), insight(id="T2")]), encoding="utf8")
    out = tmp_path / "eval" / "ab_insights.md"
    key = build_ab(tmp_path, out, seed=7)
    text = out.read_text(encoding="utf8")
    low = text.lower()
    assert not re.search(r"\b(old|new|baseline|current)\b", low)
    assert "memo" not in low and "insight" not in low and "**" not in text
    assert "A1" in text and "B1" in text and "truth" in low and "fact error" in low
    stored = json.loads((tmp_path / "eval" / "ab_insights.key.json").read_text(encoding="utf8"))
    assert stored == key and sorted(key["sets"].values()) == ["insights", "memos"] and key["seed"] == 7
    assert sorted(key["sets"]) == ["A", "B"]
    # same number of items per set (the larger set is sampled down)
    assert text.count("\n- A") == text.count("\n- B") == 2
    again = build_ab(tmp_path, out, seed=7)
    assert again == key
