"""Aggregate film-review trips (review_v*/coach_part*.json) into per-segment coach numbers.

usage: hoop-tape-miner coach-summary --review <run>/review_v1 [--official <run>/official.json]
                                     [--segments "A:0-302,B:302-1000,..."] [--out summary.json]
Times are our-video seconds. Each trip is assigned to the segment containing its start time.
Every segment also gets `four_factors` (eFG%, TOV% live/dead, ORB%, FT rate = FTM/FGA, possessions, points per
possession and the "factor that decided the game" line; method notes in `four_factors.method`) and `ppp` (points per
trip by type: transition / half_court / second_chance / unknown, plus after_live_turnover). Only the whole game
(`all`) uses --official; stretches use the reviewed trips alone. Trip types and second chances are decided with the
whole game as context.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .official import recorded


def _t0(x):
    return x.get("start", x.get("t0"))


def _back(x):
    td = x.get("transition_defence")
    if isinstance(td, dict):
        return td.get("back")
    return td if isinstance(td, (int, float)) else None


def _num(v):
    return v if isinstance(v, (int, float)) else 0


def _head(x):
    """Result keyword: the v2 enum value, or the first word of a v1 free-text result."""
    return str(x.get("result")) if x.get("schema") == 2 else str(x.get("result")).split(" ")[0].split("(")[0]


def _scored(x):
    """v2: made2/made3, or foul_ft with at least one FT made; v1: result starts with made or FT."""
    if x.get("schema") == 2:
        fts = x.get("fts") if isinstance(x.get("fts"), dict) else {}
        return x.get("result") in ("made2", "made3") or (x.get("result") == "foul_ft" and (fts.get("made") or 0) > 0)
    return str(x.get("result")).startswith(("made", "FT"))


def _foul_team(x, f):
    if x.get("schema") == 2:
        return f.get("by_team") or "unclear"
    who = str(f.get("who", "")).lower()
    return "us" if who.startswith("us") or (x.get("offence") == "them" and not who.startswith("them")) else "them"


# ---- Four Factors and points per trip type -------------------------------------------------------------------
# Dean Oliver's Four Factors with his weights; every percentage is in percent (0-100, one decimal).
WEIGHTS = {"efg": 0.4, "tov": 0.25, "orb": 0.2, "ft": 0.15}
FACTOR_NAMES = {"efg": "shooting (eFG%)", "tov": "turnovers (TOV%)", "orb": "offensive rebounding (ORB%)",
                "ft": "free throws (FT rate)"}
TRANSITION_S = 8.0     # our rule: first shot / foul within 8 s of the trip start t0 = transition, later = half-court
MIN_POSS = 15          # fewer possessions for a side: the deciding factor is "unclear"
MIN_WEIGHTED_GAP = 1.0  # a top weighted gap below 1 point is too small to name
TRIP_TYPES = ("transition", "half_court", "second_chance", "unknown")
_TRANSITION_ENTRY = ("transition", "early_offense")
_HALFCOURT_ENTRY = ("halfcourt_set", "BLOB/SLOB inbound", "BLOB", "SLOB", "after_FT")
_LIVE_CAUSES = ("steal_on_ball",)
_DEAD_CAUSES = ("travel", "charge", "out_of_bounds", "violation", "shot_clock", "shot_clock/violation",
                "offensive_foul", "three_seconds", "double_dribble")
METHOD = {
    "possessions": "count of reviewed trips minus second-chance trips (an offensive rebound continues the "
                   "possession); without reviewed trips, the estimate FGA - ORB + TOV + 0.44*FTA",
    "efg": "(FGM + 0.5*3PM) / FGA",
    "tov": "TOV / possessions; live = the defence gained the ball in play (steal), dead = the ball went dead",
    "orb": "ORB / (ORB + opponent DRB) over our missed field goals whose rebound is known (the trip's oreb_crash "
           "got/rebound, else which team has the next trip); rebounds of missed free throws are not counted",
    "ft_rate": "FTM / FGA (Oliver's definition; the league sheet records makes reliably)",
    "shooting_sources": "official makes when official.json is given; attempts from the official sheet only when it "
                        "records them, else official makes + reviewed misses; FTA = reviewed attempts + official "
                        "makes the review did not see (a lower bound)",
    "trip_types": "second_chance = trip right after the same team's missed shot that the defence did not "
                  "rebound, or entry OREB_putback (also after a missed free throw); else "
                  "`transition` field, else entry transition/early_offense vs half-court entries, else our rule: "
                  f"first shot or foul within {TRANSITION_S:g} s of t0 = transition, later = half_court; else "
                  "unknown. after_live_turnover overlaps the others: trips right after the other team's live-ball "
                  "turnover",
    "decided": f"largest weighted gap (weights {WEIGHTS['efg']}/{WEIGHTS['tov']}/{WEIGHTS['orb']}/{WEIGHTS['ft']} "
               f"x percentage points); unclear below {MIN_POSS} possessions a side or a top weighted gap below "
               f"{MIN_WEIGHTED_GAP:g}",
}


def _pct(a, b, nd=1):
    return round(100 * a / b, nd) if b else None


def _ratio(a, b, nd=2):
    return round(a / b, nd) if b else None


def _v2(x):
    return x.get("schema") == 2 and x.get("offence") in ("us", "them")


def trip_points(x) -> int:
    """Points a v2 trip scored: the made shot plus made free throws (and-ones included)."""
    pts = {"made2": 2, "made3": 3}.get(x.get("result"), 0)
    fts = x.get("fts") if isinstance(x.get("fts"), dict) else {}
    return pts + (fts.get("made") or 0 if x.get("result") in ("made2", "made3", "foul_ft") else 0)


def turnover_kind(x) -> str | None:
    """live | dead | unknown for a turnover trip (the `turnover_kind` field, else the cause), None otherwise."""
    if x.get("result") != "turnover":
        return None
    if x.get("turnover_kind") in ("live", "dead"):
        return x["turnover_kind"]
    cause = str(x.get("turnover_cause") or "")
    return "live" if cause in _LIVE_CAUSES else "dead" if cause in _DEAD_CAUSES else "unknown"


def _first_action_t(x):
    for k in ("shot", "foul"):
        o = x.get(k)
        if isinstance(o, dict) and isinstance(o.get("t"), (int, float)):
            return o["t"]
    return None


def _kind(x, second: bool) -> str:
    if second or x.get("entry") == "OREB_putback":
        return "second_chance"
    if isinstance(x.get("transition"), bool):
        return "transition" if x["transition"] else "half_court"
    if x.get("entry") in _TRANSITION_ENTRY:
        return "transition"
    if x.get("entry") in _HALFCOURT_ENTRY:
        return "half_court"
    t0, ta = _t0(x), _first_action_t(x)
    if isinstance(t0, (int, float)) and ta is not None:
        return "transition" if ta - t0 <= TRANSITION_S else "half_court"
    return "unknown"


def _rebound_side(x):
    o = x.get("oreb_crash")
    if isinstance(o, dict):
        got = o.get("got", o.get("rebound"))
        if got in ("us", "them"):
            return got
    return None


def annotate(trips: list[dict]) -> list[dict]:
    """Copies of the v2 trips (offence us/them) in time order with derived keys, using the whole game as context:
    `_points`, `_kind` (TRIP_TYPES), `_after_live_to`, `_tov_kind`, `_reb` (missed shot: "orb" | "drb" | None)."""
    xs = sorted((dict(x) for x in trips if _v2(x)), key=lambda x: (_t0(x) if _t0(x) is not None else 1e12,
                                                                   x.get("trip") or 0))
    for i, x in enumerate(xs):
        prev = xs[i - 1] if i else None
        nxt = xs[i + 1] if i + 1 < len(xs) else None
        second = bool(prev and prev["offence"] == x["offence"] and prev.get("result") == "missed"
                      and prev["_reb"] != "drb")
        x["_points"] = trip_points(x)
        x["_kind"] = _kind(x, second)
        x["_tov_kind"] = turnover_kind(x)
        x["_after_live_to"] = bool(prev and prev["offence"] != x["offence"] and turnover_kind(prev) == "live")
        x["_reb"] = None
        if x.get("result") == "missed":
            got = _rebound_side(x) or (nxt["offence"] if nxt else None)
            x["_reb"] = None if got is None else "orb" if got == x["offence"] else "drb"
    return xs


def _annotated(trips):
    return trips if all("_kind" in x for x in trips) else annotate(trips)


def ppp(trips: list[dict]) -> dict:
    """Points per trip by trip type for us and them: {side: {type: {trips, points, ppp}}}."""
    xs = _annotated(trips)
    out = {}
    for side in ("us", "them"):
        off = [x for x in xs if x["offence"] == side]
        groups = {k: [x for x in off if x["_kind"] == k] for k in TRIP_TYPES}
        groups["after_live_turnover"] = [x for x in off if x["_after_live_to"]]
        out[side] = {k: {"trips": len(g), "points": sum(x["_points"] for x in g),
                         "ppp": _ratio(sum(x["_points"] for x in g), len(g))} for k, g in groups.items()}
    return out


def _review_counts(off: list[dict]) -> dict:
    shots = [x for x in off if x.get("result") in ("made2", "made3", "missed")]
    fts = [x["fts"] for x in off if isinstance(x.get("fts"), dict)]
    return {"fgm": sum(x["result"] != "missed" for x in shots), "fg3m": sum(x["result"] == "made3" for x in shots),
            "miss": sum(x["result"] == "missed" for x in shots),
            "ftm": sum(f.get("made") or 0 for f in fts), "fta": sum(f.get("att") or 0 for f in fts),
            "tov": sum(x["_tov_kind"] is not None for x in off),
            "tov_live": sum(x["_tov_kind"] == "live" for x in off),
            "tov_dead": sum(x["_tov_kind"] == "dead" for x in off),
            "orb": sum(x["_reb"] == "orb" for x in off), "orb_chances": sum(x["_reb"] is not None for x in off),
            "trips": len(off), "second": sum(x["_kind"] == "second_chance" for x in off),
            "points": sum(x["_points"] for x in off)}


def _side_factors(side: str, xs: list[dict], off_json: dict | None, rec: dict) -> dict:
    r = _review_counts([x for x in xs if x["offence"] == side])
    tot = ((off_json or {}).get("totals") or {}).get(side) or {}
    have_review = r["trips"] > 0
    src = {}
    if off_json and tot.get("FGM-A"):
        fgm, fg3m = tot["FGM-A"]["made"], (tot.get("3PM-A") or {}).get("made", 0)
        ftm = (tot.get("FTM-A") or {}).get("made", 0)
        if rec["attempts"]:
            fga, fta = tot["FGM-A"]["att"], (tot.get("FTM-A") or {}).get("att", 0)
            src["shooting"] = "official"
        else:
            fga = fgm + r["miss"]
            fta = r["fta"] + max(0, ftm - r["ftm"])
            src["shooting"] = "official makes + reviewed misses"
    else:
        fgm, fg3m, ftm, fta = r["fgm"], r["fg3m"], r["ftm"], r["fta"]
        fga = r["fgm"] + r["miss"]
        src["shooting"] = "review"
    if have_review:
        tov, live, dead = r["tov"], r["tov_live"], r["tov_dead"]
        orb, chances = r["orb"], r["orb_chances"]
        poss = r["trips"] - r["second"]
        src["turnovers"] = src["rebounds"] = "review"
        poss_src = "review trips"
    else:
        tov = tot.get("TOV") if rec["turnovers"] else None
        live = dead = None
        orb = tot.get("ORB") if rec["rebounds"] else None
        chances = None
        src["turnovers"] = "official" if tov is not None else None
        src["rebounds"] = "official" if orb is not None else None
        poss = (round(fga - orb + tov + 0.44 * fta, 1) if None not in (tov, orb) and fga else None)
        poss_src = "estimate FGA - ORB + TOV + 0.44*FTA" if poss is not None else None
    return {"possessions": poss, "possessions_source": poss_src,
            "fgm": fgm, "fg3m": fg3m, "fga": fga, "ftm": ftm, "fta": fta,
            "tov": tov, "tov_live": live, "tov_dead": dead,
            "tov_unknown": None if tov is None or live is None else tov - live - dead,
            "orb": orb, "orb_chances": chances,
            "efg_pct": _pct(fgm + 0.5 * fg3m, fga), "tov_pct": _pct(tov, poss) if tov is not None else None,
            "tov_live_pct": _pct(live, poss) if live is not None else None,
            "tov_dead_pct": _pct(dead, poss) if dead is not None else None,
            "orb_pct": _pct(orb, chances) if chances else None, "ft_rate_pct": _pct(ftm, fga),
            "points": r["points"] if have_review else None,
            "points_official": tot.get("PTS"),
            "ppp": _ratio(r["points"], poss) if have_review and poss else None,
            "sources": src}


def decided(us: dict, them: dict, min_poss: int = MIN_POSS) -> dict:
    """The factor with the largest weighted gap (+ = favours us), stated with numbers, or status "unclear"."""
    vals = {"efg": ("efg_pct", 1), "tov": ("tov_pct", -1), "orb": ("orb_pct", 1), "ft": ("ft_rate_pct", 1)}
    gaps, weighted = {}, {}
    for f, (key, sign) in vals.items():
        a, b = us.get(key), them.get(key)
        if a is not None and b is not None:
            gaps[f] = round(sign * (a - b), 1)
            weighted[f] = round(WEIGHTS[f] * gaps[f], 2)
    out = {"status": "unclear", "factor": None, "favours": None, "gap": None, "weighted": weighted}
    pu, pt = us.get("possessions"), them.get("possessions")
    if pu is None or pt is None or min(pu, pt) < min_poss:
        out["text"] = (f"Deciding factor unclear: too few possessions (us {pu}, them {pt}; "
                       f"need {min_poss} each).")
        return out
    if not weighted:
        out["text"] = "Deciding factor unclear: no factor has numbers for both teams."
        return out
    f = max(weighted, key=lambda k: abs(weighted[k]))
    if abs(weighted[f]) < MIN_WEIGHTED_GAP:
        out["text"] = f"Deciding factor unclear: every weighted gap is below {MIN_WEIGHTED_GAP:g} point."
        return out
    key = vals[f][0]
    fav = "us" if weighted[f] > 0 else "them"
    out.update(status="ok", factor=f, favours=fav, gap=gaps[f],
               text=(f"The factor that decided the game: {FACTOR_NAMES[f]}, us {us[key]} vs them {them[key]} "
                     f"({abs(gaps[f])} percentage points in favour of {fav}; weighted {abs(weighted[f])})."))
    return out


def four_factors(trips: list[dict], official: dict | None = None, min_poss: int = MIN_POSS) -> dict:
    """Four Factors for us and them from reviewed v2 trips, merged with official.json counts where it has them."""
    xs = _annotated(trips)
    rec = recorded(official) if official else {"attempts": False, "turnovers": False, "rebounds": False}
    out = {s: _side_factors(s, xs, official, rec) for s in ("us", "them")}
    out["decided"] = decided(out["us"], out["them"], min_poss)
    out["method"] = METHOD
    return out


def summarise(trips, official: dict | None = None):
    out = {}
    for side in ("us", "them"):
        off = [x for x in trips if x.get("offence") == side]
        res = Counter(_head(x) for x in off)
        trans = [x for x in off if x.get("entry") in ("transition", "early_offense")]
        out[side] = {
            "trips": len(off),
            "results": dict(res),
            "turnovers": sum(1 for x in off if str(x.get("result")).startswith("turnover")),
            "transition_trips": len(trans),
            "transition_scores": sum(1 for x in trans if _scored(x)),
            "halfcourt_scores": sum(1 for x in off if x.get("entry") not in ("transition", "early_offense")
                                    and _scored(x)),
            "primary_action": dict(Counter(x.get("primary_action") for x in off).most_common(6)),
            "avg_paint_touches": round(sum(_num(x.get("paint_touches")) for x in off) / max(len(off), 1), 2),
            "avg_ball_stops": round(sum(_num(x.get("ball_stops")) for x in off) / max(len(off), 1), 2),
            "avg_reversals": round(sum(_num(x.get("ball_reversals")) for x in off) / max(len(off), 1), 2),
            # defenders back when this side ran transition (i.e. the OTHER team's transition defence)
            "opp_back_in_our_transition": [b for b in (_back(x) for x in trans) if b is not None],
        }
    fouls = Counter()
    for x in trips:
        f = x.get("foul")
        if isinstance(f, dict):
            fouls[f"{_foul_team(x, f)}:{f.get('type')}"] += 1
    out["fouls"] = dict(fouls)
    ann = _annotated([x for x in trips if _v2(x)])
    out["four_factors"] = four_factors(ann, official)
    out["ppp"] = ppp(ann)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-summary")
    ap.add_argument("--review", required=True)
    ap.add_argument("--segments", default="")
    ap.add_argument("--out")
    ap.add_argument("--official", help="official.json: makes, free throws and points for the whole-game Four Factors")
    a = ap.parse_args(argv)
    pid_start = {}  # fallback when a reviewer omitted trip times: possession start from part*.json
    for p in sorted(Path(a.review).glob("part*.json")):
        d = json.loads(p.read_text(encoding="utf8"))
        for poss in d if isinstance(d, list) else d.get("possessions", []):
            pid_start[poss["pid"]] = poss["start"]
    trips = []
    for p in sorted(Path(a.review).glob("coach_part*.json")):
        for x in json.loads(p.read_text(encoding="utf8")):
            if _t0(x) is None and x.get("pid") in pid_start:
                x["start"] = pid_start[x["pid"]]
            trips.append(x)
    trips = [x for x in trips if not _v2(x)] + annotate(trips)
    off = json.loads(Path(a.official).read_text(encoding="utf8")) if a.official else None
    segs = [("all", 0, 1e9)]
    for s in filter(None, a.segments.split(",")):
        name, rng = s.split(":")
        t0, t1 = rng.split("-")
        segs.append((name, float(t0), float(t1)))
    res = {name: summarise([x for x in trips if _t0(x) is not None and t0 <= _t0(x) < t1],
                           off if name == "all" else None) for name, t0, t1 in segs}
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf8")
    print(text)


if __name__ == "__main__":
    main()
