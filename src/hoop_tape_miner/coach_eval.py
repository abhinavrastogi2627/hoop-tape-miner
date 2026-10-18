"""Measure the coach review: facts against the official feed, and a structural lint of coaching insights.

usage: hoop-tape-miner coach-eval --review <run>/review_v1 [--official official.json] [--insights FILE] --label NAME
Reads coach_part*.json (+ part*.json for missing trip times) and official.json; writes <review>/eval/<label>.json
and appends one line to <review>/eval/log.md. The official sheet records makes and fouls only, so facts are scored
as points recall/precision against the score flow and per-player PTS/PF errors against the box score.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

V1_RESULTS = ("made2", "made3", "FT", "missed", "turnover", "foul_no_FT", "end_period", "unclear")
GENERIC = ("communicate better", "be more aggressive", "play harder", "stay focused", "work harder", "more energy",
           "加强沟通", "提高专注", "更积极", "更努力", "打得更硬", "注意力集中", "保持专注")
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?:\.\d)?\b")
_WHY = re.compile(r"因为|导致|所以|原因|由于|结果|because|so that|leads? to|caused|→")
_DRILL = re.compile(r"练|训练|drill|practi[cs]e", re.I)
_TARGET = re.compile(r"目标|target|[≤≥<>]\s*\d|\d+\s*(次|%|人|秒|分)", re.I)


def trip_times(x: dict) -> tuple[float | None, float | None]:
    """(start, end) video seconds from any of the field names reviewers used."""
    for a, b in (("t0", "t1"), ("start", "end"), ("t_start", "t_end")):
        if x.get(a) is not None:
            return x[a], x.get(b, x[a])
    return None, None


def is_v2(x: dict) -> bool:
    return x.get("schema") == 2


def _shot(x: dict) -> dict:
    return x.get("shot") if isinstance(x.get("shot"), dict) else {}


def _fts(x: dict) -> dict:
    return x.get("fts") if isinstance(x.get("fts"), dict) else {}


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def ref_time(x: dict) -> float | None:
    """When the trip's points happened: v2 shot.t, else v2 foul.t, else the trip end."""
    if is_v2(x):
        foul = x.get("foul") if isinstance(x.get("foul"), dict) else {}
        for t in (_shot(x).get("t"), foul.get("t")):
            if isinstance(t, (int, float)) and not isinstance(t, bool):
                return t
    return trip_times(x)[1]


def made_shot(x: dict) -> int:
    """Points of the trip's made field goal (0 when none or unclear)."""
    if is_v2(x):
        sh = _shot(x)
        return _int(sh.get("points")) if sh.get("made") is True and x.get("result") != "unclear" else 0
    r = str(x.get("result"))
    return 0 if r.startswith("unclear") else 3 if "made3" in r else 2 if "made2" in r else 0


def ft_made(x: dict) -> int:
    """Free throws made on the trip."""
    if is_v2(x):
        return 0 if x.get("result") == "unclear" else _int(_fts(x).get("made"))
    r = str(x.get("result"))
    ft = re.search(r"FT\s*\(?\s*(\d)\s*/\s*(\d)", r)
    return int(ft.group(1)) if ft and not r.startswith("unclear") else 0


def scoring(x: dict) -> list[tuple[str | None, int]]:
    """(jersey, points) parts of the trip's score: v2 shot and free throws apart, v1 one scorer for all."""
    if is_v2(x):
        if x.get("result") in (None, "unclear"):
            return []
        out = [(_shot(x).get("shooter"), made_shot(x))] if made_shot(x) else []
        return out + ([(_fts(x).get("shooter"), ft_made(x))] if ft_made(x) else [])
    p = trip_points(x) or 0
    return [(jersey(x.get("scorer_or_shooter")), p)] if p else []


def result_head(x: dict) -> str:
    if is_v2(x):
        return str(x.get("result"))
    return str(x.get("result")).split(" ")[0].split("(")[0]


def trip_points(x: dict) -> int | None:
    """Points scored on the trip (shot + free throws made); None when the result is unclear."""
    if is_v2(x):
        return None if x.get("result") in (None, "unclear") else made_shot(x) + ft_made(x)
    r = str(x.get("result"))
    if r == "None" or r.startswith("unclear"):
        return None
    pts = 3 if "made3" in r else 2 if "made2" in r else 0
    ft = re.search(r"FT\s*\(?\s*(\d)\s*/\s*(\d)", r)
    return pts + (int(ft.group(1)) if ft else 0)


def jersey(v) -> str | None:
    """A single confident jersey number from a free-text field, else None ("45 or 13", "unclear", "19?")."""
    s = str(v or "").strip()
    if not s or "?" in s or re.search(r"\bor\b", s) or s.lower().startswith("unclear"):
        return None
    m = re.match(r"#?(\d{1,2})\b", s)
    return m.group(1) if m else None


def foul_side(x: dict) -> tuple[str | None, str | None]:
    """(team, jersey) of the fouler; a bare number or "unclear" defaults to the defending team."""
    f = x.get("foul")
    if not isinstance(f, dict):
        return None, None
    if is_v2(x):
        return f.get("by_team"), f.get("by")
    who = str(f.get("who") or f.get("by") or "").strip()
    low = who.lower()
    if low.startswith(("us", "them")):
        return ("us" if low.startswith("us") else "them"), None
    off = x.get("offence")
    team = f.get("by_team") or ({"us": "them", "them": "us"}.get(off))
    return team, jersey(who)


def valid_v1_result(r) -> bool:
    head = str(r).split(" ")[0].split("(")[0]
    return head in V1_RESULTS and "+" not in str(r)


def _match(events: list[dict], trips: list[dict], lag: tuple[float, float]) -> int:
    """Greedy: each official event takes points from the scoring trip ending closest to (event - 15 s) in the lag window."""
    left = {id(x): trip_points(x) or 0 for x in trips}
    matched = 0
    for e in sorted(events, key=lambda e: e["our_video_t"]):
        t = e["our_video_t"]
        cands = [x for x in trips if left[id(x)] > 0 and ref_time(x) is not None
                 and t + lag[0] <= ref_time(x) <= t + lag[1]]
        if not cands:
            continue
        best = min(cands, key=lambda x: abs(ref_time(x) - (t - 15)))
        got = min(left[id(best)], e["points"])
        left[id(best)] -= got
        matched += got
    return matched


def _match_events(events: list[dict], trips: list[dict], lag: tuple[float, float]) -> Counter:
    """One-to-one: each official shot event (+2/+3) takes one made shot and each +1 one made free throw from a
    trip whose ref_time lies in the lag window (closest to event - 15 s wins)."""
    supply = {"shots": {id(x): made_shot(x) for x in trips}, "fts": {id(x): ft_made(x) for x in trips}}
    m = Counter()
    for e in sorted(events, key=lambda e: e["our_video_t"]):
        t, kind = e["our_video_t"], "fts" if e["points"] == 1 else "shots"
        left = supply[kind]
        cands = [x for x in trips if left[id(x)] > 0 and ref_time(x) is not None
                 and t + lag[0] <= ref_time(x) <= t + lag[1]]
        if not cands:
            continue
        best = min(cands, key=lambda x: abs(ref_time(x) - (t - 15)))
        m[kind] += 1
        if kind == "fts":
            left[id(best)] -= 1
        else:
            m["agree"] += left[id(best)] == e["points"]
            left[id(best)] = 0
    return m


def facts_eval(trips: list[dict], official: dict, lag: tuple[float, float] = (-40.0, 8.0)) -> dict:
    """Per team: points recall/precision vs the score flow, team points, per-player PTS/PF errors, result mix."""
    out = {}
    for side in ("us", "them"):
        off = [x for x in trips if x.get("offence") == side]
        flow = [e for e in official.get("score_flow", []) if e["team"] == side]
        events = [e for e in flow if e.get("our_video_t") is not None]  # others fall outside our video
        review_pts = sum(trip_points(x) or 0 for x in off)
        official_pts = sum(e["points"] for e in events)
        matched = _match(events, off, lag)
        box = official.get("players", {}).get(side, {})
        pts, pf = Counter(), Counter()
        unattributed = 0
        for x in off:
            for who, p in scoring(x):
                if who:
                    pts[str(who)] += p
                else:
                    unattributed += p
        fouls = [foul_side(x) for x in trips]
        for team, who in fouls:
            if team == side and who:
                pf[str(who)] += 1
        heads = Counter(result_head(x) for x in off)
        em = _match_events(events, off, lag)
        out[side] = {
            "trips": len(off),
            "unclear": heads.get("unclear", 0) + heads.get("None", 0),
            "missed": heads.get("missed", 0),
            "team_pts": [review_pts, official_pts],
            "official_pts_off_video": sum(e["points"] for e in flow) - official_pts,
            "pts_recall": round(matched / official_pts, 3) if official_pts else None,
            "pts_precision": round(matched / review_pts, 3) if review_pts else None,
            "events": {"shots": sum(e["points"] >= 2 for e in events), "fts": sum(e["points"] == 1 for e in events)},
            "events_matched": {"shots": em["shots"], "fts": em["fts"]},
            "shot_points_agree": em["agree"],
            "player_pts_abs_err": sum(abs(pts[n] - box.get(n, {}).get("PTS", 0)) for n in set(box) | set(pts)),
            "unattributed_pts": unattributed,
            "unknown_jerseys": sorted(n for n in set(pts) | set(pf) if n not in box),
            "fouls_found": sum(1 for t, _ in fouls if t == side),
            "fouls_official": sum(v.get("PF", 0) for v in box.values()),
            "player_pf_abs_err": sum(abs(pf[n] - box.get(n, {}).get("PF", 0)) for n in set(box) | set(pf)),
        }
    from .coach_schema import validate_trip  # late import: coach_schema imports this module
    bad = sum(bool(validate_trip(x)) if is_v2(x) else not valid_v1_result(x.get("result")) for x in trips)
    out["invalid_result_share"] = round(bad / max(len(trips), 1), 3)
    conf = Counter(str(x.get("confidence")) for x in trips)
    out["confidence"] = dict(conf)
    return out


def insight_lint(items: list) -> dict:
    """Structural check of coaching insights (markdown strings or insight dicts): evidence, why, drill, target."""
    r = Counter(n=len(items))
    for it in items:
        if isinstance(it, dict):
            text = " ".join(str(v) for v in it.values())
            r["with_evidence"] += len(it.get("evidence") or []) >= 2
            r["with_why"] += bool(it.get("why"))
            r["with_drill"] += bool(it.get("drill"))
            r["with_target"] += bool(it.get("target_next_game"))
        else:
            text = str(it)
            r["with_evidence"] += len(set(_TIME.findall(text))) >= 2  # distinct video times
            r["with_why"] += bool(_WHY.search(text))
            r["with_drill"] += bool(_DRILL.search(text))
            r["with_target"] += bool(_TARGET.search(text))
        r["generic_phrases"] += sum(text.lower().count(g) for g in GENERIC)
    return {k: r[k] for k in ("n", "with_evidence", "with_why", "with_drill", "with_target", "generic_phrases")}


def memo_conclusions(text: str) -> list[str]:
    """Numbered items under the last H2 whose title mentions conclusions/takeaways."""
    secs = re.split(r"^## ", text, flags=re.M)
    sec = [s for s in secs if re.match(r".*(结论|conclusion|takeaway)", s.splitlines()[0] if s else "", re.I)]
    return [m.strip() for m in re.findall(r"^\s*\d+\.\s+(.+)$", sec[-1], re.M)] if sec else []


def load_trips(review: Path) -> list[dict]:
    """All coach_part*.json trips; missing times are taken from the possession in part*.json."""
    poss = {}
    for p in sorted(review.glob("part*.json")):
        d = json.loads(p.read_text(encoding="utf8"))
        for x in d if isinstance(d, list) else d.get("possessions", []):
            poss[x["pid"]] = (x["start"], x["end"])
    trips = []
    for p in sorted(review.glob("coach_part*.json")):
        for x in json.loads(p.read_text(encoding="utf8")):
            if trip_times(x)[0] is None and x.get("pid") in poss:
                x["t0"], x["t1"] = poss[x["pid"]]
            trips.append(x)
    return trips


def _ev(side: dict) -> str:
    m, n = side["events_matched"], side["events"]
    return f"shots {m['shots']}/{n['shots']} FT {m['fts']}/{n['fts']}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-eval")
    ap.add_argument("--review", required=True)
    ap.add_argument("--official", help="default: <review>/../official.json")
    ap.add_argument("--insights", help="insights.json, or a glob inside --review such as 'memo_part*.md' "
                                       "(the numbered conclusion items are linted)")
    ap.add_argument("--label", required=True)
    a = ap.parse_args(argv)
    review = Path(a.review)
    off = Path(a.official) if a.official else review.parent / "official.json"
    res = {"label": a.label, "at": datetime.now().isoformat(timespec="seconds"),
           "facts": facts_eval(load_trips(review), json.loads(off.read_text(encoding="utf8")))}
    if a.insights:
        if a.insights.endswith(".json"):
            items = json.loads(Path(a.insights).read_text(encoding="utf8"))
        else:
            items = [c for p in sorted(review.glob(a.insights)) for c in memo_conclusions(p.read_text(encoding="utf8"))]
        res["insights"] = insight_lint(items)
    out = review / "eval"
    out.mkdir(exist_ok=True)
    (out / f"{a.label}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf8")
    f = res["facts"]
    line = (f"- {res['at']} **{a.label}**: us pts {f['us']['team_pts']} recall {f['us']['pts_recall']} "
            f"prec {f['us']['pts_precision']} events {_ev(f['us'])} playerPTS err {f['us']['player_pts_abs_err']} PF err "
            f"{f['us']['player_pf_abs_err']}; them pts {f['them']['team_pts']} recall {f['them']['pts_recall']} events {_ev(f['them'])}; "
            f"invalid {f['invalid_result_share']}" + (f"; insights {res['insights']}" if "insights" in res else ""))
    with open(out / "log.md", "a", encoding="utf8") as fh:
        fh.write(line + "\n")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
