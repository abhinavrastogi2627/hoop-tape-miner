"""Season page from synthetic game folders: results, periods, Four Factors, targets checked in the next game,
recurring themes, pooled on/off and lineups with shrinkage, missing pieces, publish link + hub, pre-game brief."""
import json
from pathlib import Path

import pytest

from hoop_tape_miner import publish, render_html, season


def write(p: Path, data) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf8")
    return p


def ff(us_efg, them_efg, us_poss=40):
    side = lambda efg, poss: {"efg_pct": efg, "tov_pct": 20.0, "orb_pct": 30.0, "ft_rate_pct": 15.0,
                              "possessions": poss, "ppp": 0.8}
    return {"us": side(us_efg, us_poss), "them": side(them_efg, 42), "decided": {"factor": "efg"}}


def make_game(root: Path, slug: str, folder: str, us: int, them: int, *, half=None, summary=None, insights=None,
              pm=None, lineup=None, flow=None, periods=((0, 600), (700, 1300))) -> Path:
    g = root / "teams" / slug / folder
    result = {"us": us, "them": them}
    if half:
        result["halftime"] = {"us": half[0], "them": half[1]}
    write(g / "game.json", {"us": {"team": "Example Owls", "hex": "#d1495b"},
                            "them": {"team": slug.replace("-", " ").title()},
                            "periods": [list(p) for p in periods], "result": result})
    review = g / "run" / "review_v1"
    review.mkdir(parents=True)
    if summary is not None:
        write(review / "summary.json", {"all": summary})
    if insights is not None:
        write(review / "insights.json", insights)
    if pm is not None:
        write(review / "plusminus.json", pm)
    if lineup is not None:
        write(review / "lineup_intervals.json", lineup)
    if flow is not None:
        write(g / "run" / "official.json", {"score_flow": flow})
    return g


def insight(i, kb, target, rule="Get back first."):
    return {"id": i, "kb": kb, "claim": "c", "why": "w", "rule": rule, "drill": "d", "target_next_game": target}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(render_html, "duration_s", lambda p: 60.0)
    write(tmp_path / "team.json", {"team": "Example Owls", "languages": ["zh", "en"]})
    # game 1: old, only the result (no review pieces)
    make_game(tmp_path, "red-foxes", "2000-01-01", 30, 38)
    # game 2: full review; targets for game 3
    five = {f"us#{n}": [[0, 600]] for n in (4, 7, 9, 10, 13)}
    five["us#21"] = [[700, 1300]]
    for n in (4, 7, 9, 10):
        five[f"us#{n}"].append([700, 1300])
    flow2 = [{"team": "us", "points": 2, "our_video_t": 100}, {"team": "them", "points": 3, "our_video_t": 200},
             {"team": "us", "points": 2, "our_video_t": 800}]
    make_game(tmp_path, "blue-owls", "2000-01-08", 40, 35, half=(20, 15), summary={
        "us": {"transition_scores": 4}, "them": {"transition_scores": 9}, "fouls": {"us:shooting": 7},
        "four_factors": ff(45.0, 50.0)},
        insights=[insight("T1", ["transition-defence"], "Their fast-break scores (summary them.transition_scores) "
                                                       "at most 4 (was 9); everyone sprints back."),
                  insight("T2", ["foul-discipline"], "Our shooting fouls (summary fouls us:shooting) at most 4 (was 7)"),
                  insight("T3", ["spacing"], "Better spacing on every trip.")],
        pm={"us#4": {"on": {"seconds": 1200, "for": 4, "against": 3, "net": 1}, "off": {"for": 0, "against": 0, "net": 0}},
            "us#21": {"on": {"seconds": 600, "for": 2, "against": 0, "net": 2}, "off": {"for": 2, "against": 3, "net": -1}}},
        lineup=five, flow=flow2)
    # game 3: a redo folder (-v2) of the same date replaces the plain one
    make_game(tmp_path, "red-foxes", "2000-01-15", 1, 1)
    make_game(tmp_path, "red-foxes", "2000-01-15-v2", 33, 30, half=(15, 18), summary={
        "us": {"transition_scores": 5}, "them": {"transition_scores": 3}, "fouls": {"us:shooting": 6},
        "four_factors": ff(52.0, 44.0)},
        insights=[insight("T1", ["transition-defence", "rebounding"], "Their fast-break scores at most 3.")],
        pm={"us#4": {"on": {"seconds": 1000, "for": 30, "against": 20, "net": 10}, "off": {"for": 3, "against": 10, "net": -7}}})
    return tmp_path


def test_games_are_read_oldest_first_and_redo_folders_win(ws):
    keys = [f"{f.parent.name}/{f.name}" for f in season.game_folders(ws)]
    assert keys == ["red-foxes/2000-01-01", "blue-owls/2000-01-08", "red-foxes/2000-01-15-v2"]


def test_season_results_record_and_periods(ws):
    s, games = season.build(ws)
    assert s["season"] == "2000-01-01_2000-01-15" and s["games"] == 3
    assert s["record"] == {"W": 2, "L": 1, "T": 0, "unknown": 0, "for": 103, "against": 103}
    assert [g["result"]["outcome"] for g in s["results"]] == ["L", "W", "W"]
    # halves only where game.json has them; game 1 has none and no score flow -> missing, not invented
    assert s["period_totals"] == [{"period": 1, "games": 2, "for": 35, "against": 33},
                                  {"period": 2, "games": 2, "for": 38, "against": 32}]
    assert set(s["results"][0]["missing"]) >= {"periods", "four_factors", "insights", "plusminus", "lineups"}
    assert s["results"][0]["four_factors"] is None
    assert s["results"][2]["four_factors"]["us"]["efg"] == 52.0


def test_season_id_from_team_json(ws):
    write(ws / "team.json", {"team": "Example Owls", "season": "autumn-2000"})
    assert season.build(ws)[0]["season"] == "autumn-2000"


def test_periods_from_score_flow_when_no_halftime(tmp_path):
    g = make_game(tmp_path, "a", "2000-02-01", 4, 3,
                  flow=[{"team": "us", "points": 2, "our_video_t": 10}, {"team": "them", "points": 3, "our_video_t": 650},
                        {"team": "us", "points": 2, "our_video_t": 900}])
    d = season.load_game_data(g)
    assert d["periods"] == [[2, 3], [2, 0]] and d["periods_source"] == "official score flow"


def test_targets_from_one_game_checked_in_the_next(ws):
    s, _ = season.build(ws)
    check = s["targets_checked"][1]
    assert check["from"] == "blue-owls/2000-01-08" and check["checked_in"] == "red-foxes/2000-01-15-v2"
    t1, t2, t3 = check["targets"]
    assert t1["status"] == "met"  # 3 <= 4; the second clause names no number
    assert [c["status"] for c in t1["clauses"]] == ["met", "not_measurable"]
    assert t1["clauses"][0]["actual"] == 3 and t1["clauses"][0]["metric"] == "summary.them.transition_scores"
    assert t2["status"] == "missed" and t2["clauses"][0]["actual"] == 6
    assert t3["status"] == "not_measurable"
    assert s["targets_checked"][0]["targets"] == []  # game 1 had no insights
    assert [t["insight"] for t in s["next_targets"]] == ["T1"]


def test_structured_target_and_missing_next_number():
    nxt = {"_summary": {"all": {"us": {"turnovers": 9}}}}
    prev = {"insights": [{"id": "A", "kb": ["x"], "target_next_game": "fewer turnovers",
                          "target": {"metric": "summary.us.turnovers", "op": "<=", "value": 10}},
                         {"id": "B", "kb": ["y"], "target_next_game": "Steals (summary us.steals) at least 3"}]}
    a, b = season.check_targets(prev, nxt)
    assert a["status"] == "met" and b["status"] == "not_measurable"


def test_target_check_is_the_shared_structured_target():
    nxt = {"_summary": {"all": {"us": {"turnovers": 9}}}, "_official": {"totals": {"us": {"FTM": 4}}}}
    prev = {"insights": [{"id": "A", "kb": ["x"], "target_next_game": "turnovers at most 8",
                          "target_check": {"number": "all.us.turnovers", "max": 8}},
                         {"id": "B", "kb": ["y"], "target_next_game": "free throws made 3 to 6",
                          "target_check": {"number": "official.totals.us.FTM", "min": 3, "max": 6}}]}
    a, b = season.check_targets(prev, nxt)
    assert a["status"] == "missed" and a["clauses"][0]["actual"] == 9
    assert b["status"] == "met" and len(b["clauses"]) == 2


def test_recurring_themes_count_games(ws):
    th = {t["kb"]: t for t in season.build(ws)[0]["themes"]}
    assert th["transition-defence"]["games"] == 2 and th["transition-defence"]["recurring"]
    assert th["spacing"]["games"] == 1 and not th["spacing"]["recurring"]


def test_shrinkage_rule():
    assert season.raw_per10(3, 120) == 15.0 and season.shrunk_per10(3, 120) == 1.36  # 2 lucky minutes stay small
    assert season.shrunk_per10(10, 20 * 60) == 2.5  # 10 net in 20 min: raw 5.0, shrunk halfway to 0
    assert abs(season.shrunk_per10(10, 600 * 60)) < season.raw_per10(10, 600 * 60) + 1e-9


def test_players_pooled_with_shrinkage_and_flags(ws):
    players = {p["player"]: p for p in season.build(ws)[0]["players"]}
    p4 = players["4"]
    assert p4["games"] == 2 and p4["minutes"] == round(2200 / 60, 1)
    assert p4["on"]["net"] == 11 and p4["on"]["per10_raw"] == round(110 / (2200 / 60), 2)
    assert p4["on"]["per10_shrunk"] == round(110 / (2200 / 60 + season.PRIOR_MIN), 2)
    # off: game length 1200 s each, minus on seconds -> 0 s + 200 s
    assert p4["off"]["minutes"] == round(200 / 60, 1) and p4["off"]["net"] == -7
    assert p4["small_sample"]  # 2 games < 3
    assert players["21"]["games"] == 1 and players["21"]["small_sample"]


def test_lineups_from_intervals_and_score_flow(ws):
    units = {"-".join(u["lineup"]): u for u in season.build(ws)[0]["lineups"]}
    a, b = units["4-7-9-10-13"], units["4-7-9-10-21"]
    assert a["minutes"] == 10.0 and (a["for"], a["against"]) == (2, 3)
    assert b["minutes"] == 10.0 and (b["for"], b["against"]) == (2, 0)
    assert b["per10_shrunk"] == round(10 * 2 / (10 + season.PRIOR_MIN), 2) and b["small_sample"]


def test_lineup_units_skip_slices_without_five():
    lineup = {"us#1": [[0, 10]], "us#2": [[0, 10]], "us#3": [[0, 10]], "us#4": [[0, 10]], "us#5": [[0, 5]],
              "them#9": [[0, 10]]}
    units = season.lineup_units(lineup, [(1.0, "us", 2), (7.0, "them", 3)])
    assert units == {"1-2-3-4-5": {"seconds": 5.0, "for": 2, "against": 0}}


def test_main_writes_bilingual_page_and_charts(ws, capsys):
    season.main([])
    out = ws / "season" / "2000-01-01_2000-01-15"
    data = json.loads((out / "season.json").read_text(encoding="utf8"))
    assert data["kind"] == "season" and "_summary" not in json.dumps(data)
    en = (out / "README.en.md").read_text(encoding="utf8")
    zh = (out / "README.md").read_text(encoding="utf8")
    assert "# Season 2000-01-01_2000-01-15" in en and "赛季总览" in zh
    assert "Last game's targets checked" in en and "**met**" in en and "not measurable" in en
    assert "transition-defence (recurring)" in en and "small sample" in en
    assert "Our rule" in en and "我们的规则" in zh
    svg = (out / "ff_efg.en.svg").read_text(encoding="utf8")
    assert svg.startswith("<svg") and "<script" not in svg and svg.count("<circle") == 4  # 2 games x us/them
    page = (out / "index.html").read_text(encoding="utf8")
    assert 'data-result="season"' in page and "2–1" in page and "data:image/svg+xml;base64," in page
    assert "missing" in capsys.readouterr().out


def test_out_option_and_no_html(ws, tmp_path):
    out = tmp_path / "elsewhere"
    season.main(["--out", str(out), "--no-html"])
    assert (out / "season.json").exists() and not (out / "index.html").exists()
    assert not (ws / "season").exists()


def test_brief_names_themes_targets_and_opponent_history(ws):
    season.main(["--brief", "--opponent", "Red Foxes", "--no-html"])
    out = ws / "season" / "2000-01-01_2000-01-15"
    en = (out / "brief.en.md").read_text(encoding="utf8")
    assert "transition defence, in 2 games" in en and "Their fast-break scores at most 3." in en
    assert "games against them so far: 2" in en and "30 to 38, a loss" in en and "33 to 30, a win" in en
    assert en.startswith("# ")  # the header line is a note, narrate does not read it
    zh = (out / "brief.zh.md").read_text(encoding="utf8")
    assert "赛季简报" in zh and "我们输" in zh
    season.main(["--brief", "--opponent", "Green Bees", "--no-html"])
    assert "no earlier game against them" in (out / "brief.en.md").read_text(encoding="utf8")


def test_brief_without_recurring_themes_names_the_last_games(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    make_game(tmp_path, "a", "2000-03-01", 10, 12, insights=[insight("X", ["press-break"], "t")])
    s, games = season.build(tmp_path)
    en = season.brief(s, games, "en")
    assert "No theme has come up in more than one game yet. Last game's themes: press break." in en


def test_brief_is_narratable_paragraphs(ws):
    from hoop_tape_miner import narrate
    s, games = season.build(ws)
    paras = narrate.paragraphs(season.brief(s, games, "en"))
    assert paras and not any(p.startswith("#") for p in paras)


def test_publish_gives_season_a_stable_link_on_top_of_the_hub(ws):
    season.main([])
    out = ws / "season" / "2000-01-01_2000-01-15"
    game = ws / "teams" / "blue-owls" / "2000-01-08"
    write(game / "README.md", "# Game report\n")
    publish.main([str(game), str(out)])
    reg = json.loads((ws / "publish.json").read_text(encoding="utf8"))
    tok = reg["reports"]["season/2000-01-01_2000-01-15"]
    page = (ws / "site" / tok / "index.html").read_text(encoding="utf8")
    assert 'data-result="season"' in page and "Content-Security-Policy" in page
    hub = (ws / "site" / reg["hub"] / "index.html").read_text(encoding="utf8")
    assert hub.index(f"../{tok}/") < hub.index(f"../{reg['reports']['teams/blue-owls/2000-01-08']}/")
    assert 'class="season"' in hub
    season.main([])
    publish.main([str(out)])  # re-publishing keeps the link
    assert json.loads((ws / "publish.json").read_text(encoding="utf8"))["reports"]["season/2000-01-01_2000-01-15"] == tok


def test_no_games_exits(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit):
        season.main([])
