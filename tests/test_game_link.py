"""Game -> training loop: the latest game's insights seed a session, game vs practice make rates in the summary."""
import json
from pathlib import Path

import pytest

from hoop_tape_miner import game_link, train_new, train_summary


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf8")


def trip(shooter, made, zone, offence="us", fts=None):
    return {"offence": offence, "schema": 2, "shot": {"t": 1.0, "shooter": shooter, "made": made, "zone": zone},
            "fts": fts}


def game(root: Path, slug: str, date: str, us_box: dict, trips=None, insights=None, attempts=False):
    folder = root / "teams" / slug / date
    run = folder / "run"
    write(folder / "game.json", {"name": date, "us": {"team": "Us", "focus_player": "17"}, "them": {"team": "Opp"},
                                 "result": {"us": 40, "them": 38}})
    box = {j: {"PTS": 0, "2PM-A": {"made": m2, "att": a2 if attempts else m2},
               "3PM-A": {"made": m3, "att": a3 if attempts else m3},
               "FTM-A": {"made": ft, "att": fta if attempts else ft}}
           for j, (m2, a2, m3, a3, ft, fta) in us_box.items()}
    write(run / "official.json", {"final": {}, "players": {"us": box, "them": {}}, "totals": {}, "score_flow": []})
    if trips is not None:
        write(run / "review_v1" / "coach_part1.json", trips)
    if insights is not None:
        write(run / "review_v1" / "insights.json", insights)
    return folder


INSIGHTS = [
    {"id": "T1", "player": None, "kb": ["transition-defence"], "claim": "They ran on our misses.",
     "rule": "Guards are safeties.", "drill": "Line-up transition", "target_next_game": "At most 3 against."},
    {"id": "P17-1", "player": "17", "kb": ["shot-selection"], "claim": "#17 forced pull-ups.",
     "rule": "Drive and kick.", "drill": "Catch-and-shoot from the wing", "target_next_game": "2 kick-out assists."},
    {"id": "P9-1", "player": "9", "kb": ["boxout"], "claim": "#9 lost boxouts.", "rule": "Hit first.",
     "drill": "Boxout ladder", "target_next_game": "3 boxouts."},
]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    # an older game where the official sheet records attempts
    game(tmp_path, "red-foxes", "2026-09-01", {"17": (3, 8, 1, 4, 2, 4)}, attempts=True)
    # the latest game before the session: makes only on the sheet, misses from the film review
    trips = [trip("17", True, "rim"), trip("17", False, "rim"), trip("17", False, "midrange"),
             trip(17, True, "three"), trip("17", None, "three"), trip("4", True, "rim"),
             trip("17", False, "three", offence="them"), trip(None, False, "rim"),
             {"offence": "us", "schema": 2, "shot": None, "fts": {"shooter": "17", "made": 1, "att": 2}}]
    game(tmp_path, "blue-owls", "2026-10-01", {"17": (1, 0, 1, 0, 1, 0)}, trips=trips, insights=INSIGHTS)
    # a game after the session: never used for it
    game(tmp_path, "red-foxes", "2026-11-01", {"17": (9, 9, 9, 9, 9, 9)}, insights=INSIGHTS[:1])
    return tmp_path


def test_jersey_from_session_player_or_profile(ws):
    assert game_link.jersey_for({"player": "17"}, {}) == "17"
    assert game_link.jersey_for({"player": "alex"}, {"focus_player": "17"}) == "17"
    assert game_link.jersey_for({"player": "alex", "jersey": "8"}, {"focus_player": "17"}) == "8"
    assert game_link.jersey_for({"player": "alex"}, {}) is None


def test_workspace_root_from_a_session_folder(ws):
    assert game_link.workspace_of(ws / "players" / "alex" / "training" / "2026-10-20") == ws
    assert game_link.workspace_of(ws / "elsewhere" / "2026-10-20") is None


def test_focus_from_the_latest_game_before_the_session(ws):
    f = game_link.focus(ws, "17", "2026-10-20")
    assert f["game"] == "blue-owls/2026-10-01" and f["date"] == "2026-10-01"
    assert [i["id"] for i in f["insights"]] == ["P17-1", "T1"]  # the player's first, other players' left out
    assert f["insights"][0]["scope"] == "player" and f["insights"][0]["drill"].startswith("Catch-and-shoot")
    assert game_link.focus(ws, "17", "2026-08-01") is None


def test_game_shooting_official_attempts_else_film_review(ws):
    games = game_link.games_for(ws, "17", "2026-10-20")
    old, last = (game_link.game_shooting(g, "17") for g in games)
    assert old["two"] == dict(made=3, att=8, source="official")
    assert old["rim"] is None  # official sheets have no zones
    assert last["two"] == dict(made=1, att=3, source="film review")  # rim make, rim miss, mid miss; unclear apart
    assert last["three"] == dict(made=1, att=1, source="film review")
    assert last["rim"] == dict(made=1, att=2, source="film review")
    assert last["ft"] == dict(made=1, att=2, source="film review")
    assert last["unclear"] == 1


def test_compare_labels_small_samples_and_keeps_units(ws):
    practice = {"zones": {"ft": {"made": 14, "att": 20, "pct": 0.7}, "rim": {"made": 5, "att": 6, "pct": 0.833},
                          "mid": {"made": 4, "att": 10, "pct": 0.4}, "three": {"made": 3, "att": 12, "pct": 0.25}},
                "totals": {"finish": {"made": 8, "att": 10, "pct": 0.8}}}
    cmp = game_link.compare(ws, "17", "2026-10-20", practice)
    rows = {r["category"]: r for r in cmp["rows"]}
    ft = rows["ft"]
    assert ft["practice"] == dict(made=14, att=20, pct=0.7)
    assert ft["last_game"] == dict(made=1, att=2, pct=0.5, source="film review")
    assert ft["games"] == dict(made=3, att=6, pct=0.5, source="official + film review", n=2)
    assert ft["gap_pp"] == -20 and ft["small_sample"] is True and ft["sample"] == "small sample"
    assert rows["three"]["sample"] == "small sample"  # 1/4 official + 1/1 film = 5 attempts
    assert rows["non_rim_two"]["sample"] == "too few" and rows["non_rim_two"]["games"]["att"] == 1
    assert rows["rim"]["unattributed"] == 1 and ft["unattributed"] == 1  # one of our shots has no shooter
    assert rows["two"]["practice"] == dict(made=17, att=26, pct=0.654)  # rim + paint + mid shots + finishes
    assert rows["rim"]["practice"] == dict(made=13, att=16, pct=0.812)
    assert rows["rim"]["games"]["n"] == 1  # only the reviewed game has zones
    assert cmp["last_game"] == "blue-owls/2026-10-01" and cmp["jersey"] == "17"


def test_compare_without_games_is_unclear(tmp_path):
    cmp = game_link.compare(tmp_path, "17", "2026-10-20", {"zones": {}, "totals": {}})
    assert cmp["rows"] == [] and cmp["last_game"] is None


def test_train_new_seeds_game_focus(ws):
    def joiner(videos, out, long_side):
        return [dict(file=str(videos[0]), start=0.0, duration=60.0)]
    v = ws / "phone.mp4"
    v.write_bytes(b"x")
    folder = train_new.create([v], "17", "2026-10-20", joiner=joiner)
    s = json.loads((folder / "session.json").read_text(encoding="utf8"))
    assert s["jersey"] == "17"
    assert s["game_focus"]["game"] == "blue-owls/2026-10-01"


def test_facts_show_game_focus_and_game_vs_practice(ws):
    sm = {"game_focus": game_link.focus(ws, "17", "2026-10-20"),
          "game_vs_practice": game_link.compare(ws, "17", "2026-10-20", {
              "zones": {"ft": {"made": 14, "att": 20, "pct": 0.7}}, "totals": {}})}
    text = "\n".join(train_summary.game_facts(sm))
    assert "## Game focus" in text and "P17-1" in text and "Catch-and-shoot" in text
    assert "## Game vs practice" in text and "small sample" in text and "70%" in text


def test_summary_game_loop_uses_session_focus_else_latest_game(ws):
    folder = ws / "players" / "alex" / "training" / "2026-10-20"
    sm = {"zones": {"three": {"made": 3, "att": 12, "pct": 0.25}}, "totals": {}}
    out = train_summary.game_loop(folder, {"player": "alex", "jersey": "17", "date": "2026-10-20"}, sm)
    assert out["game_focus"]["game"] == "blue-owls/2026-10-01"
    assert [r["category"] for r in out["game_vs_practice"]["rows"]] == ["three"]
    kept = train_summary.game_loop(folder, {"player": "alex", "jersey": "17", "date": "2026-10-20",
                                            "game_focus": {"game": "x", "jersey": "17", "insights": []}}, sm)
    assert kept["game_focus"]["game"] == "x"
    assert train_summary.game_loop(ws / "loose", {"player": "17", "date": "2026-10-20"}, sm)["game_vs_practice"] is None
