"""Opponent rematch dossier (`scout`): past games against one opponent pooled from synthetic game folders."""
import json
from pathlib import Path

import pytest

from hoop_tape_miner import new_game, scout


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf8")


def side(fgm, fg3m, fga, ftm, fta, tov, poss, orb, chances):
    return dict(fgm=fgm, fg3m=fg3m, fga=fga, ftm=ftm, fta=fta, tov=tov, possessions=poss, orb=orb,
                orb_chances=chances, efg_pct=None, tov_pct=None, orb_pct=None, ft_rate_pct=None)


def ppp(trans, half, second):
    return {k: {"trips": t, "points": p, "ppp": round(p / t, 2) if t else None}
            for k, (t, p) in (("transition", trans), ("half_court", half), ("second_chance", second),
                              ("unknown", (0, 0)), ("after_live_turnover", (0, 0)))}


def make_game(root: Path, slug: str, date: str, us: int, them: int, *, half=None, players_them=None,
              players_us=None, summary=None, insights=None, run_name=None, folder_name=None, flow=None,
              attempts=False):
    folder = root / "teams" / slug / (folder_name or date)
    run = root / "media" / slug / (run_name or date) / "run"
    write(folder / "game.json", {"name": f"{date} vs Opp", "run": str(run), "us": {"team": "Us"},
                                 "them": {"team": "Opp Team"},
                                 "result": {"us": us, "them": them, "us_side": "home", "them_side": "away",
                                            "halftime": half or {"us": None, "them": None}}})

    def box(pl):
        out = {}
        for j, (pts, m2, m3, ftm, pf) in (pl or {}).items():
            out[j] = {"PTS": pts, "2PM-A": {"made": m2, "att": m2 + (3 if attempts else 0)},
                      "3PM-A": {"made": m3, "att": m3}, "FTM-A": {"made": ftm, "att": ftm + (1 if attempts else 0)},
                      "PF": pf}
        return out
    write(run / "official.json", {"final": {"us": {"pts": us}, "them": {"pts": them}},
                                  "players": {"us": box(players_us), "them": box(players_them)},
                                  "totals": {"us": {"PTS": us}, "them": {"PTS": them}},
                                  "score_flow": flow or []})
    if summary is not None:
        write(run / "review_v1" / "summary.json", summary)
    if insights is not None:
        write(run / "review_v1" / "insights.json", insights)
    return folder


def ff(us_side, them_side, decided):
    return {"us": us_side, "them": them_side, "decided": decided}


@pytest.fixture
def ws(tmp_path):
    """Two games against 'red-foxes' (a loss with a review and insights, a win without a review) and one
    game against another team in between, whose summary answers the first game's targets."""
    flow = [dict(team="them", points=2, score_us=0, score_them=2), dict(team="them", points=3, score_us=0, score_them=5),
            dict(team="us", points=2, score_us=2, score_them=5), dict(team="them", points=2, score_us=2, score_them=7),
            dict(team="us", points=2, score_us=4, score_them=7), dict(team="us", points=2, score_us=6, score_them=7),
            dict(team="us", points=3, score_us=9, score_them=7)]
    s1 = {"all": {"us": {"transition_scores": 2, "turnovers": 12}, "them": {"transition_scores": 6},
                  "four_factors": ff(side(10, 1, 30, 4, 8, 12, 40, 5, 20), side(14, 2, 32, 6, 10, 8, 41, 8, 22),
                                     {"status": "ok", "factor": "efg", "favours": "them",
                                      "text": "The factor that decided the game: shooting (eFG%), us 35.0 vs them 46.9."}),
                  "ppp": {"us": ppp((5, 4), (30, 20), (5, 2)), "them": ppp((10, 14), (28, 20), (6, 4))}}}
    insights = [
        {"id": "T1", "player": None, "kb": ["transition-defence"], "claim": "They ran on our misses.",
         "drill": "Line-up transition", "target_next_game": "At most 3 transition scores against.",
         "numbers": {"all.them.transition_scores": 6, "features.31-1.numbers_back_2s": 1},
         "target_check": {"number": "all.them.transition_scores", "max": 3}},
        {"id": "P17-1", "player": "17", "kb": ["shot-selection"], "claim": "#17 forced pull-ups.",
         "drill": "Catch-and-shoot", "target_next_game": "Fewer than 8 turnovers as a team.",
         "numbers": {"all.us.turnovers": 12}},
    ]
    make_game(tmp_path, "red-foxes", "2026-09-01", 30, 38, half={"us": 10, "them": 20}, flow=flow,
              players_them={"4": (12, 4, 1, 1, 2), "9": (10, 5, 0, 0, 4), "21": (6, 3, 0, 0, 1)},
              players_us={"17": (8, 4, 0, 0, 3)}, summary=s1, insights=insights)
    s_other = {"all": {"us": {"turnovers": 9}, "them": {"transition_scores": 2}}}
    make_game(tmp_path, "blue-owls", "2026-09-08", 40, 35, summary=s_other)
    make_game(tmp_path, "red-foxes", "2026-10-01", 41, 39, players_them={"4": (20, 7, 2, 0, 1), "11": (9, 3, 1, 0, 0)})
    return tmp_path


def test_record_scorers_and_unclear_factors(ws):
    sc = scout.build(ws / "teams" / "red-foxes", ws)
    assert sc["record"] == {"games": 2, "w": 1, "l": 1, "t": 0, "unclear": 0}
    assert [g["date"] for g in sc["games"]] == ["2026-09-01", "2026-10-01"]
    assert sc["games"][0]["result"] == "L" and sc["games"][0]["score"] == {"us": 30, "them": 38}
    top = sc["their_scorers"]
    assert [p["jersey"] for p in top[:2]] == ["4", "9"]
    assert top[0] == dict(jersey="4", games=2, pts=32, ppg=16.0, fgm2=11, fgm3=3, ftm=1, fouls=3,
                          fg_att=None, ft_att=None)
    # the second game has no review: its factors are unclear, the pool uses the reviewed game only
    assert sc["games"][1]["four_factors"] is None and sc["games"][1]["decided"].startswith("unclear")
    pool = sc["four_factors"]
    assert pool["games"] == 1
    assert pool["them"]["efg_pct"] == 46.9 and pool["us"]["tov_pct"] == 30.0
    assert sc["ppp"]["them"]["transition"] == {"trips": 10, "points": 14, "ppp": 1.4}


def test_score_flow_runs_and_decided_text(ws):
    g = scout.build(ws / "teams" / "red-foxes", ws)["games"][0]
    assert g["runs"] == {"us": 7, "them": 5}  # longest unanswered runs
    assert g["decided"].startswith("The factor that decided the game: shooting")
    assert g["halftime"] == {"us": 10, "them": 20}


def test_targets_checked_against_the_next_game_of_any_opponent(ws):
    sc = scout.build(ws / "teams" / "red-foxes", ws)
    t1, p1 = sc["targets"]
    assert t1["next_game"] == "blue-owls/2026-09-08"
    assert t1["status"] == "met"
    assert t1["values"]["all.them.transition_scores"] == {"before": 6, "after": 2}
    assert t1["values"]["features.31-1.numbers_back_2s"]["after"] == "not comparable"
    assert p1["status"] == "unclear" and p1["values"]["all.us.turnovers"] == {"before": 12, "after": 9}


def test_re_reviews_of_one_game_count_once(ws):
    make_game(ws, "red-foxes", "2026-10-01", 41, 39, folder_name="2026-10-01-v2", run_name="2026-10-01",
              summary={"all": {}}, players_them={"4": (20, 7, 2, 0, 1)})
    sc = scout.build(ws / "teams" / "red-foxes", ws)
    assert sc["record"]["games"] == 2
    assert sc["games"][1]["folder"] == "2026-10-01-v2"  # the one with a review wins


def test_before_excludes_the_upcoming_game_and_nothing_invented(ws, tmp_path):
    sc = scout.build(ws / "teams" / "red-foxes", ws, before="2026-10-01")
    assert sc["record"]["games"] == 1
    empty = scout.build(ws / "teams" / "nobody", ws)
    assert empty["record"]["games"] == 0 and empty["four_factors"] is None
    md = scout.markdown(empty)
    assert "unclear" in md.lower() or "no past games" in md.lower()


def test_markdown_lists_jerseys_only_and_marks_unclear(ws):
    md = scout.markdown(scout.build(ws / "teams" / "red-foxes", ws))
    assert "#4" in md and "1-1" in md
    assert "unclear" in md
    assert "eFG%" in md and "transition" in md


def test_cli_writes_json_and_md(ws, monkeypatch, capsys):
    monkeypatch.setenv("HOOP_WORKSPACE", str(ws))
    scout.main(["--opponent", "Red Foxes"])
    assert json.loads((ws / "teams" / "red-foxes" / "scout.json").read_text(encoding="utf8"))["record"]["games"] == 2
    assert (ws / "teams" / "red-foxes" / "scout.md").exists()


def test_new_game_dossier_includes_scout(ws, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(ws))
    new_game.scaffold("Red Foxes", "2026-11-01", dossier=True)
    sc = json.loads((ws / "teams" / "red-foxes" / "scout.json").read_text(encoding="utf8"))
    assert sc["record"]["games"] == 2 and sc["before"] == "2026-11-01"
    assert "scout.md" in (ws / "teams" / "red-foxes" / "README.md").read_text(encoding="utf8")


def test_official_with_attempts_gives_their_fg_attempts(tmp_path):
    make_game(tmp_path, "x", "2026-09-01", 20, 22, players_them={"5": (10, 4, 0, 2, 1)}, attempts=True)
    p = scout.build(tmp_path / "teams" / "x", tmp_path)["their_scorers"][0]
    assert p["fg_att"] == 7 and p["ft_att"] == 3
