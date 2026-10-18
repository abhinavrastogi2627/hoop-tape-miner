"""Aggregate film-review trips (review_v*/coach_part*.json) into per-segment coach numbers.

usage: hoop-tape-miner coach-summary --review <run>/review_v1 [--segments "A:0-302,B:302-1000,..."] [--out summary.json]
Times are our-video seconds. Each trip is assigned to the segment containing its start time.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


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


def summarise(trips):
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
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-summary")
    ap.add_argument("--review", required=True)
    ap.add_argument("--segments", default="")
    ap.add_argument("--out")
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
    segs = [("all", 0, 1e9)]
    for s in filter(None, a.segments.split(",")):
        name, rng = s.split(":")
        t0, t1 = rng.split("-")
        segs.append((name, float(t0), float(t1)))
    res = {name: summarise([x for x in trips if _t0(x) is not None and t0 <= _t0(x) < t1]) for name, t0, t1 in segs}
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf8")
    print(text)


if __name__ == "__main__":
    main()
