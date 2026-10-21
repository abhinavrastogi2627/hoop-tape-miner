"""Game -> training loop: shared helpers for train-new and train-summary (not a stage).

* `focus`    the latest game before a session (where the player's jersey is on our official box score): its
             insights.json for that jersey first, then the team insights, with drill and next-game target. train-new
             stores it in session.json `game_focus`; the report writer turns it into plan.json drills.
* `compare`  game vs practice make rates for the same jersey. Game numbers come from the official box score when
             the sheet records attempts, else from the film review's trips (shot.shooter / fts.shooter on our trips);
             practice numbers from the session's summary (`zones`, `totals.finish`). Categories: ft, two, three
             (official or review), rim and non-rim two (review only). A side under TOO_FEW / SMALL_N attempts is
             labelled "too few" / "small sample"; a missing side stays None ("unclear"). `unattributed` counts our
             reviewed shots without a shooter in the review-sourced games: the player's film attempts are a lower bound.
Games are read from <workspace>/teams/*/*/ (scout.all_games: re-reviews of one game count once).
"""
from __future__ import annotations

from pathlib import Path

from . import scout
from .coach_eval import load_trips

SMALL_N = 20  # fewer attempts than this on either side: a small sample, say so
TOO_FEW = 5   # fewer than this: too few to read anything into the gap
# practice zones (training review) per category; finishes count as two-point attempts at the rim
PRACTICE = {"ft": (("ft",), False), "two": (("rim", "paint", "mid"), True), "three": (("three",), False),
            "rim": (("rim",), True), "non_rim_two": (("paint", "mid"), False)}
# film-review shot zones (coach schema) per category
REVIEW_ZONES = {"two": ("rim", "paint_non_rim", "midrange"), "three": ("three",), "rim": ("rim",),
                "non_rim_two": ("paint_non_rim", "midrange")}
OFFICIAL_KEYS = {"two": ("2PM-A",), "three": ("3PM-A",), "ft": ("FTM-A",)}
CATEGORIES = ("ft", "two", "three", "rim", "non_rim_two")


def workspace_of(session_folder: Path) -> Path | None:
    """<root> for a session folder <root>/players/<player>/training/<name>, else None."""
    f = Path(session_folder)
    if f.parent.name == "training" and len(f.parents) > 3 and f.parents[2].name == "players":
        return f.parents[3]
    return None


def jersey_for(session: dict, prof: dict) -> str | None:
    """session.json `jersey`, else a numeric `player`, else team.json focus_player; None when none is known or when
    `jersey` is explicitly null (a guest who plays for no team of ours: no game link)."""
    if "jersey" in session and session["jersey"] is None:
        return None
    for v in (session.get("jersey"), session.get("player") if str(session.get("player") or "").isdigit() else None,
              prof.get("focus_player")):
        if v not in (None, ""):
            return str(v)
    return None


def _on_roster(g: dict, jersey: str) -> bool:
    us = ((g["official"] or {}).get("players") or {}).get("us") or {}
    if us:
        return jersey in {str(k) for k in us}
    return str((g["game"].get("us") or {}).get("focus_player") or "") == jersey


def games_for(root: Path, jersey: str, before: str) -> list[dict]:
    """Our games on or before `before` (YYYY-MM-DD) with this jersey on the roster, oldest first."""
    return [g for g in scout.all_games(root) if g["date"] <= before and _on_roster(g, jersey)]


def focus(root: Path, jersey: str, before: str) -> dict | None:
    """The latest game's insights for this jersey (scope player) then the team's (scope team); None without a game."""
    games = games_for(root, jersey, before)
    if not games:
        return None
    g = games[-1]
    items = []
    for it in g["insights"] or []:
        p = it.get("player")
        scope = "team" if p in (None, "") else "player" if str(p) == jersey else None
        if scope:
            items.append(dict(id=it.get("id"), scope=scope, kb=it.get("kb") or [], claim=it.get("claim"),
                              rule=it.get("rule"), drill=it.get("drill"), target_next_game=it.get("target_next_game")))
    items.sort(key=lambda x: x["scope"] != "player")
    return dict(game=scout.label(g), date=g["date"], jersey=jersey, insights=items,
                note=None if g["insights"] is not None else "unclear: that game has no insights.json")


def _tally(made: int, att: int, source: str) -> dict:
    return dict(made=made, att=att, source=source)


def _attempts_known(off: dict | None) -> bool:
    return bool(off) and scout._attempts_known(off)


def game_shooting(g: dict, jersey: str) -> dict:
    """{category: {made, att, source} | None, unclear: n} for one game. Official when the sheet records attempts,
    else the film review (our trips, shooter = jersey; made None counts as unclear); None when neither has it."""
    out: dict = {c: None for c in CATEGORIES}
    off = g["official"]
    line = (((off or {}).get("players") or {}).get("us") or {}).get(jersey)
    if line and _attempts_known(off):
        for c, keys in OFFICIAL_KEYS.items():
            out[c] = _tally(sum((line.get(k) or {}).get("made", 0) for k in keys),
                            sum((line.get(k) or {}).get("att", 0) for k in keys), "official")
    trips = load_trips(g["review"]) if g["review"].is_dir() else []
    mine = [x for x in trips if x.get("offence") == "us"]
    shots = [x["shot"] for x in mine if isinstance(x.get("shot"), dict) and str(x["shot"].get("shooter")) == jersey]
    fts = [x["fts"] for x in mine if isinstance(x.get("fts"), dict) and str(x["fts"].get("shooter")) == jersey]
    out["unclear"] = sum(s.get("made") is None for s in shots)
    # our reviewed shots with no shooter: some may be this player's, so his film-review attempts are a lower bound
    out["unattributed"] = sum(isinstance(x.get("shot"), dict) and x["shot"].get("shooter") in (None, "")
                              for x in mine)
    decided = [s for s in shots if s.get("made") in (True, False)]
    if trips:
        for c, zones in REVIEW_ZONES.items():
            if out[c] is None:
                z = [s for s in decided if s.get("zone") in zones]
                out[c] = _tally(sum(s["made"] for s in z), len(z), "film review")
        if out["ft"] is None:
            out["ft"] = _tally(sum(f.get("made") or 0 for f in fts), sum(f.get("att") or 0 for f in fts), "film review")
    return out


def _pct(made, att):
    return round(made / att, 3) if att else None


def _pool(rows: list[dict | None]) -> dict | None:
    rows = [r for r in rows if r]
    if not rows:
        return None
    made, att = sum(r["made"] for r in rows), sum(r["att"] for r in rows)
    srcs = list(dict.fromkeys(r["source"] for r in rows))
    return dict(made=made, att=att, pct=_pct(made, att), source=" + ".join(srcs), n=len(rows))


def practice_rate(summary: dict, category: str) -> dict | None:
    """Practice made / att for a category from a training summary (zones + finishes); None without attempts."""
    zones, finishes = PRACTICE[category]
    parts = [(summary.get("zones") or {}).get(z) for z in zones]
    if finishes:
        parts.append((summary.get("totals") or {}).get("finish"))
    parts = [p for p in parts if p]
    made, att = sum(p.get("made", 0) for p in parts), sum(p.get("att", 0) for p in parts)
    return dict(made=made, att=att, pct=_pct(made, att)) if att else None


def compare(root: Path, jersey: str, before: str, practice: dict) -> dict:
    """Game vs practice rows per category where both sides have attempts: last game, all games to date, practice,
    gap in percentage points (all games minus practice) and a small-sample flag."""
    games = games_for(root, jersey, before)
    per = [game_shooting(g, jersey) for g in games]
    rows = []
    for c in CATEGORIES:
        pr = practice_rate(practice, c)
        pooled = _pool([p[c] for p in per])
        if not pr or not pooled or not pooled["att"]:
            continue
        last = per[-1][c]
        last = dict(last, pct=_pct(last["made"], last["att"])) if last and last["att"] else None
        n = min(pooled["att"], pr["att"])
        unattributed = sum(p["unattributed"] for p in per if p[c] and p[c]["source"] == "film review")
        rows.append(dict(category=c, practice=pr, last_game=last, games=pooled,
                         gap_pp=round(100 * (pooled["pct"] - pr["pct"])), small_sample=n < SMALL_N,
                         sample="too few" if n < TOO_FEW else "small sample" if n < SMALL_N else "ok",
                         unattributed=unattributed))
    return dict(jersey=jersey, last_game=scout.label(games[-1]) if games else None, games=len(games),
                small_n=SMALL_N, rows=rows,
                note="Game attempts are defended and practice attempts mostly are not; read a gap as a direction, "
                     "not a size. Official numbers only where the sheet records attempts.")
