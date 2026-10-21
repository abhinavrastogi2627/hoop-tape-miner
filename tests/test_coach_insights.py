"""Coach insights: validation against trips, KB and summary; blind A/B sheet."""
import json
import re

import pytest

from hoop_tape_miner.coach_insights import build_ab, check_critic, kb_slugs, main, validate_insights

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
    slack = insight(evidence=[{"t": 104.0, "pid": 1, "what": "x"},
                              {"t": 112.5, "pid": 1, "trip": 1, "what": "just after the trip, within 3 s"}])
    assert validate_insights([slack], TRIPS, KB, SUMMARY) == []
    counter = insight(counter_examples=[{"t": 500.0, "pid": 4, "trip": 1, "what": "orphan counter-example"}])
    assert validate_insights([counter], TRIPS, KB, SUMMARY)


def test_evidence_must_name_an_existing_trip_and_fall_inside_it():
    no_pid = insight(evidence=[{"t": 104.0, "what": "x"}, {"t": 305.5, "pid": 4, "trip": 1, "what": "y"}])
    assert any("pid" in e for e in validate_insights([no_pid], TRIPS, KB, SUMMARY))
    ghost = insight(evidence=[{"t": 104.0, "pid": 1, "trip": 1, "what": "x"},
                              {"t": 305.5, "pid": 9, "trip": 1, "what": "y"}])
    assert any("pid 9" in e and "not a trip" in e for e in validate_insights([ghost], TRIPS, KB, SUMMARY))
    wrong_trip = insight(evidence=[{"t": 104.0, "pid": 1, "trip": 2, "what": "x"},
                                   {"t": 305.5, "pid": 4, "trip": 1, "what": "y"}])
    assert any("trip 2" in e for e in validate_insights([wrong_trip], TRIPS, KB, SUMMARY))
    # inside some trip, but not the one it cites: the old check let this through
    swapped = insight(evidence=[{"t": 305.5, "pid": 1, "trip": 1, "what": "x"},
                                {"t": 104.0, "pid": 4, "trip": 1, "what": "y"}])
    errs = validate_insights([swapped], TRIPS, KB, SUMMARY)
    assert any("305.5" in e and "pid 1" in e for e in errs)
    two = TRIPS + [{"schema": 2, "pid": 1, "trip": 2, "t0": 110.0, "t1": 130.0, "offence": "us"}]
    vague = insight(evidence=[{"t": 104.0, "pid": 1, "what": "x"}, {"t": 305.5, "pid": 4, "trip": 1, "what": "y"}])
    assert any("name the trip" in e for e in validate_insights([vague], two, KB, SUMMARY))


def test_player_must_be_on_the_roster():
    p = insight(id="P17-1", player="17")
    assert validate_insights([p], TRIPS, KB, SUMMARY, roster={"17", "4"}) == []
    errs = validate_insights([insight(id="P71-1", player="71")], TRIPS, KB, SUMMARY, roster={"17", "4"})
    assert any("71" in e and "roster" in e for e in errs)
    assert validate_insights([insight(id="P71-1", player="71")], TRIPS, KB, SUMMARY) == []  # no roster known


def test_unknown_kb_slug_fails():
    errs = validate_insights([insight(kb=["zone-offence"])], TRIPS, KB, SUMMARY)
    assert any("zone-offence" in e for e in errs)
    assert validate_insights([insight(kb=[])], TRIPS, KB, SUMMARY)


def test_number_mismatch_fails():
    errs = validate_insights([insight(numbers={"all.us.turnovers": 7})], TRIPS, KB, SUMMARY)
    assert any("all.us.turnovers" in e for e in errs)
    assert validate_insights([insight(numbers={"all.us.turnovers": 9})], TRIPS, KB, SUMMARY) == []


def test_unresolved_number_fails_unless_marked_unknown():
    errs = validate_insights([insight(numbers={"all.us.pace_typo": 12})], TRIPS, KB, SUMMARY)
    assert any("all.us.pace_typo" in e and "not found" in e for e in errs)
    errs = validate_insights([insight(numbers={"features.1-1.numbers_back_2s": 1})], TRIPS, KB, SUMMARY)
    assert any("features.json" in e for e in errs)  # no features file: cannot be checked, so it fails
    feats = {"1-1": {"numbers_back_2s": 1}}
    assert validate_insights([insight(numbers={"features.1-1.numbers_back_2s": 1})], TRIPS, KB, SUMMARY, feats) == []
    assert validate_insights([insight(numbers={"all.us.pace": "unknown"})], TRIPS, KB, SUMMARY) == []
    official = {"totals": {"us": {"FTM": 7}}}
    src = {"official": official, "plusminus": {"us#4": {"net": -3}}}
    ok = insight(numbers={"official.totals.us.FTM": 7, "plusminus.us#4.net": -3})
    assert validate_insights([ok], TRIPS, KB, SUMMARY, sources=src) == []
    bad = insight(numbers={"official.totals.us.FTM": 8})
    assert any("official.totals.us.FTM" in e for e in validate_insights([bad], TRIPS, KB, SUMMARY, sources=src))


def test_dropped_insight_fails():
    errs = validate_insights([insight(critic={"verdict": "drop", "note": "not on film"})], TRIPS, KB, SUMMARY)
    assert any("drop" in e for e in errs)
    assert validate_insights([insight(critic=None)], TRIPS, KB, SUMMARY) == []  # the verdict lives in critic.json
    assert validate_insights([insight(rule="")], TRIPS, KB, SUMMARY)
    assert validate_insights([], TRIPS, KB, SUMMARY)


def test_kb_slugs_parses_headings(tmp_path):
    p = tmp_path / "kb.md"
    p.write_text("# KB\n\n### KB-transition-defence\ntext\n\n### KB-foul-discipline\n", encoding="utf8")
    assert kb_slugs(p) == {"transition-defence", "foul-discipline"}


def review_folder(tmp_path, items=None):
    """A review folder with trips, summary, a manifest with two sheets, insights and a KB file; returns the KB path."""
    (tmp_path / "coach_part1.json").write_text(json.dumps(TRIPS), encoding="utf8")
    (tmp_path / "summary.json").write_text(json.dumps(SUMMARY), encoding="utf8")
    manifest = [{"pid": 1, "start": 100.0, "end": 110.0, "sheets": ["p001_0.jpg"]},
                {"pid": 4, "start": 300.0, "end": 312.0, "sheets": ["p004_0.jpg", "p004_1.jpg"]}]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    for s in ("p001_0.jpg", "p004_0.jpg", "p004_1.jpg"):
        (tmp_path / s).write_bytes(b"jpg")
    (tmp_path / "insights.json").write_text(json.dumps(items or [insight(critic=None)]), encoding="utf8")
    kb = tmp_path / "kb.md"
    kb.write_text("### KB-transition-defence\n", encoding="utf8")
    return kb


def write_critic(folder, verdicts):
    (folder / "critic.json").write_text(json.dumps({"verdicts": verdicts}), encoding="utf8")


KEEP = {"id": "T1", "verdict": "keep", "note": "both moments checked", "reopened": ["p001_0.jpg", "p004_0.jpg"]}


def test_writer_check_skips_the_critic_and_full_check_needs_it(tmp_path, capsys):
    kb = review_folder(tmp_path)
    assert main(["check", "--review", str(tmp_path), "--kb", str(kb), "--no-critic"]) == 0
    with pytest.raises(SystemExit):
        main(["check", "--review", str(tmp_path), "--kb", str(kb)])
    assert "critic.json" in capsys.readouterr().out


def test_critic_signs_and_a_later_edit_breaks_the_signature(tmp_path, capsys):
    kb = review_folder(tmp_path)
    write_critic(tmp_path, [KEEP])
    assert check_critic(tmp_path) and any("not signed" in e for e in check_critic(tmp_path))
    assert main(["critic", "--review", str(tmp_path), "--kb", str(kb)]) == 0
    assert check_critic(tmp_path) == []
    assert main(["check", "--review", str(tmp_path), "--kb", str(kb)]) == 0
    items = json.loads((tmp_path / "insights.json").read_text(encoding="utf8"))
    items[0]["claim"] += " Edited after the critic."
    (tmp_path / "insights.json").write_text(json.dumps(items), encoding="utf8")
    assert any("changed after the critic" in e for e in check_critic(tmp_path))


def test_critic_verdict_needs_reopened_sheets_covering_the_evidence(tmp_path):
    review_folder(tmp_path)
    write_critic(tmp_path, [dict(KEEP, reopened=[])])
    assert any("reopened" in e for e in check_critic(tmp_path, sign=True))
    write_critic(tmp_path, [dict(KEEP, reopened=["p001_0.jpg"])])  # 305.5 is on a pid 4 sheet, not re-opened
    assert any("305.5" in e for e in check_critic(tmp_path, sign=True))
    write_critic(tmp_path, [dict(KEEP, reopened=["p001_0.jpg", "p009_0.jpg"])])
    assert any("p009_0.jpg" in e for e in check_critic(tmp_path, sign=True))
    write_critic(tmp_path, [dict(KEEP, reopened=["p001_0.jpg", "../p004_0.jpg"])])
    assert check_critic(tmp_path, sign=True)
    write_critic(tmp_path, [dict(KEEP, reopened=["p001_0.jpg", "p004_1.jpg"])])
    assert check_critic(tmp_path, sign=True) == []


def test_critic_covers_every_insight_and_the_dropped_ones(tmp_path):
    review_folder(tmp_path, [insight(critic=None), insight(id="T2", critic=None)])
    write_critic(tmp_path, [KEEP])
    assert any("T2" in e and "no verdict" in e for e in check_critic(tmp_path, sign=True))
    write_critic(tmp_path, [KEEP, dict(KEEP, id="T2", verdict="drop")])
    assert any("T2" in e and "drop" in e for e in check_critic(tmp_path, sign=True))
    review_folder(tmp_path, [insight(critic=None)])
    (tmp_path / "insights_dropped.json").write_text(json.dumps([insight(id="T2")]), encoding="utf8")
    write_critic(tmp_path, [KEEP])  # T2 dropped by the writer, no drop verdict from the critic
    assert any("T2" in e for e in check_critic(tmp_path, sign=True))
    write_critic(tmp_path, [KEEP, dict(KEEP, id="T2", verdict="drop", note="one trip only")])
    assert check_critic(tmp_path, sign=True) == []


def test_self_set_verdict_in_insights_must_match_the_critic(tmp_path):
    review_folder(tmp_path, [insight(critic={"verdict": "keep", "note": "self-certified"})])
    write_critic(tmp_path, [dict(KEEP, verdict="revise", note="moved a time")])
    assert any("critic.json" in e and "revise" in e for e in check_critic(tmp_path, sign=True))


def test_check_cli_exits_1_on_errors(tmp_path):
    kb = review_folder(tmp_path)
    assert main(["check", "--review", str(tmp_path), "--kb", str(kb), "--no-critic"]) == 0
    (tmp_path / "insights.json").write_text(json.dumps([insight(kb=["nope"])]), encoding="utf8")
    with pytest.raises(SystemExit) as e:
        main(["check", "--review", str(tmp_path), "--kb", str(kb), "--no-critic"])
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
