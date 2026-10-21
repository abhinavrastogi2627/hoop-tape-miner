"""Shot-attempt proposals from ball arcs at the rim, labelled by the official point chart.

    hoop-tape-miner shot-proposals --run RUN [--official official.json] [--review REVIEW] [--out RUN/shot_proposals.json]

Reads rim_scan.pkl (ball-sized movers around each rim, rim_scan.py) and links the blobs of each rim into arcs
(constant-velocity nearest neighbour). An arc that moves like a ball (>= 6 points, travels >= 0.6 m, ballistic fit
RMS <= 0.25 m) and passes within 0.6 m of the rim centre is a proposal; proposals at one rim within 2.5 s merge. The attacking team comes
from the rim side and the period's attack direction (possessions.pkl).

Labels never come from pixels. Each official score event (score_flow: made field goals and free throws, with
our_video_t on the video clock) takes the latest unmatched proposal of the same team between 40 s before and
5 s after its video time (the league feed lags the video; measured -2.5 .. +35.5 s, median 10 s, on a reference
game). A matched proposal is "made" with the event's points; every other proposal is "likely miss" (a missed
shot, a free throw miss, a tip, or a false arc). Without official stats every proposal is "unlabelled".

With --review, the output also scores the proposals against the reviewed trips (coach_part*.json): reviewed made
shots with a proposal near their release time, reviewed missed trips with a proposal inside, and the share of
proposals inside reviewed shot trips.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .ball import RIM_Z

LAG = (-40.0, 5.0)  # proposal t - official video t accepted for a match (s)
# Defaults picked on a reference game (see docs/optimization-backlog.md item 1): min_pts 6, rim_r 0.6 and a loose
# ballistic-fit RMS 0.25 m found the most reviewed makes for the fewest proposals outside shot trips.
ARC = dict(max_dt=0.17, gate=0.35, gate_v=0.5, min_pts=6, min_path=0.6, min_net=0.4, max_speed=16.0,
           rim_r=0.6, max_rms=0.25, merge_s=2.5)


def link_arcs(blobs: pd.DataFrame, **kw) -> list[dict]:
    """Link one rim's blobs (t, u, z) into arcs; returns every arc with its points and summary numbers.

    A blob extends the arc whose constant-velocity prediction is nearest, within gate + gate_v * speed * dt
    metres and max_dt seconds; each arc takes at most one blob per frame. Summary: n, t0, t1, path (m), net
    (start-end distance, m), speed (median m/s), t_rim / d_rim (time and distance of the closest approach to the
    rim centre u=0, z=3.05), z_max.
    """
    p = {**ARC, **kw}
    arcs, active = [], []
    for t, g in blobs.sort_values("t").groupby("t", sort=True):
        active = [a for a in active if t - a["t"][-1] <= p["max_dt"] + 1e-6]
        cand = []
        for k, (u, z) in enumerate(zip(g.u.to_numpy(float), g.z.to_numpy(float))):
            for ai, a in enumerate(active):
                dt = t - a["t"][-1]
                vu, vz = a["v"]
                d = np.hypot(u - (a["u"][-1] + vu * dt), z - (a["z"][-1] + vz * dt))
                if d <= p["gate"] + p["gate_v"] * np.hypot(vu, vz) * dt:
                    cand.append((d, k, ai))
        used_b, used_a = set(), set()
        rows = list(zip(g.u.to_numpy(float), g.z.to_numpy(float)))
        for d, k, ai in sorted(cand):
            if k in used_b or ai in used_a:
                continue
            a = active[ai]
            u, z = rows[k]
            dt = t - a["t"][-1]
            v = ((u - a["u"][-1]) / dt, (z - a["z"][-1]) / dt)
            sp = np.hypot(*v)
            if sp > p["max_speed"]:
                continue
            a["v"] = v if len(a["t"]) == 1 else (0.5 * a["v"][0] + 0.5 * v[0], 0.5 * a["v"][1] + 0.5 * v[1])
            a["t"].append(float(t)), a["u"].append(u), a["z"].append(z)
            used_b.add(k), used_a.add(ai)
        for k, (u, z) in enumerate(rows):
            if k not in used_b:
                a = {"t": [float(t)], "u": [u], "z": [z], "v": (0.0, 0.0)}
                active.append(a)
                arcs.append(a)
    out = []
    for a in arcs:
        t, u, z = (np.asarray(a[k]) for k in ("t", "u", "z"))
        step = np.hypot(np.diff(u), np.diff(z))
        dr = np.hypot(u, z - RIM_Z)
        i = int(dr.argmin())
        sp = step / np.maximum(np.diff(t), 1e-6) if len(t) > 1 else np.array([0.0])
        out.append(dict(n=len(t), t0=float(t[0]), t1=float(t[-1]), path=float(step.sum()),
                        net=float(np.hypot(u[-1] - u[0], z[-1] - z[0])), speed=float(np.median(sp)),
                        rms=fit_rms(t, u, z),
                        t_rim=float(t[i]), d_rim=float(dr[i]), u_rim=float(u[i]), z_rim=float(z[i]),
                        z_max=float(z.max()), pts=[[round(float(x), 3) for x in r] for r in zip(t, u, z)]))
    return out


def fit_rms(t, u, z) -> float:
    """RMS residual (m) of a ballistic fit: u linear and z quadratic in t. inf with fewer than 4 points."""
    t = np.asarray(t, float)
    if len(t) < 4:
        return float("inf")
    t = t - t.mean()
    ru = u - np.polyval(np.polyfit(t, u, 1), t)
    rz = z - np.polyval(np.polyfit(t, z, 2), t)
    return float(np.sqrt(np.mean(ru ** 2 + rz ** 2)))


def is_shot_arc(a: dict, **kw) -> bool:
    p = {**ARC, **kw}
    return (a["n"] >= p["min_pts"] and a["path"] >= p["min_path"] and a["net"] >= p["min_net"]
            and a["d_rim"] <= p["rim_r"] and a["rms"] <= p["max_rms"])


def propose(scan: pd.DataFrame, **kw) -> list[dict]:
    """Shot-attempt proposals from rim_scan rows: qualifying arcs per rim, merged within merge_s (the arc with
    the closest rim approach gives t). Each: t, side, n_arcs, n_pts, d_rim, arc (points of the best arc)."""
    p = {**ARC, **kw}
    props = []
    for side, g in scan.groupby("side"):
        arcs = sorted((a for a in link_arcs(g, **kw) if is_shot_arc(a, **kw)), key=lambda a: a["t_rim"])
        group: list[dict] = []
        for a in arcs + [None]:
            if group and (a is None or a["t_rim"] - group[-1]["t_rim"] > p["merge_s"]):
                best = min(group, key=lambda x: (x["d_rim"], -x["n"]))
                props.append(dict(t=round(best["t_rim"], 2), side=side, n_arcs=len(group),
                                  n_pts=sum(x["n"] for x in group), d_rim=round(best["d_rim"], 2),
                                  arc=best["pts"]))
                group = []
            if a is not None:
                group.append(a)
    return sorted(props, key=lambda x: x["t"])


def attack_team(t: float, side: str, poss: pd.DataFrame | None, sides: dict) -> str | None:
    """Team attacking `side` at video time t: the period of the possession nearest t, then its attack map."""
    if poss is None or poss.empty or not sides:
        return None
    per = poss.period[(poss.start - t).abs().idxmin()]
    for (pp, team), s in sides.items():
        if pp == per and s == side:
            return team
    return None


def label(props: list[dict], score_flow: list[dict], lag=LAG) -> tuple[list[dict], list[dict]]:
    """Label proposals from the official score events (see module doc). Returns (proposals, official events
    without a proposal). Events without our_video_t are skipped; a proposal with no team matches either team."""
    for p in props:
        p.update(label="likely miss", points=None, official_t=None)
    events = sorted((e for e in score_flow if e.get("our_video_t") is not None and e.get("points")),
                    key=lambda e: e["our_video_t"])
    unmatched = []
    for e in events:
        t = e["our_video_t"]
        c = [p for p in props if p["label"] != "made" and t + lag[0] <= p["t"] <= t + lag[1]
             and p.get("team") in (None, e.get("team"))]
        if not c:
            unmatched.append(e)
            continue
        p = max(c, key=lambda p: p["t"])
        p.update(label="made", points=int(e["points"]), official_t=e.get("official_t"), team=e.get("team"))
    return props, unmatched


def evaluate(props: list[dict], unmatched: list[dict], score_flow: list[dict], trips: list[dict] | None) -> dict:
    """Counts against the official chart and, with reviewed trips, against the review (see module doc)."""
    fg = [e for e in score_flow if e.get("our_video_t") is not None and e.get("points") in (2, 3)]
    ft = [e for e in score_flow if e.get("our_video_t") is not None and e.get("points") == 1]
    um_fg = sum(e.get("points") in (2, 3) for e in unmatched)
    out = {"proposals": len(props), "made": sum(p["label"] == "made" for p in props),
           "likely_miss": sum(p["label"] == "likely miss" for p in props),
           "official_fg": len(fg), "official_fg_matched": len(fg) - um_fg,
           "official_fg_recall": round((len(fg) - um_fg) / len(fg), 3) if fg else None,
           "official_ft_events": len(ft), "official_ft_matched": len(ft) - sum(e.get("points") == 1 for e in unmatched),
           "lag_window_s": list(LAG)}
    if trips:
        from .coach_eval import trip_times
        pt = np.array([p["t"] for p in props]) if props else np.zeros(0)
        made = [x["shot"]["t"] for x in trips if isinstance(x.get("shot"), dict)
                and isinstance(x["shot"].get("t"), (int, float)) and str(x.get("result", "")).startswith("made")]
        miss = [trip_times(x) for x in trips if x.get("result") == "missed" and trip_times(x)[0] is not None]
        shot_trips = [trip_times(x) for x in trips if x.get("result") in ("made2", "made3", "missed", "foul_ft")
                      and trip_times(x)[0] is not None]

        def near(t0, t1):
            return bool(((pt >= t0) & (pt <= t1)).any())

        inside = [any(a - 1 <= t <= b + 2 for a, b in shot_trips) for t in pt]
        out.update(review_made_with_shot_t=len(made),
                   review_made_found=sum(near(t - 1, t + 3) for t in made),
                   review_missed_trips=len(miss),
                   review_missed_found=sum(near(a - 1, b + 2) for a, b in miss),
                   proposals_in_shot_trips=int(sum(inside)),
                   proposals_outside_shot_trips=int(len(pt) - sum(inside)))
        # label agreement: proposals labelled made inside a reviewed made trip, and vice versa
        made_trips = [trip_times(x) for x in trips if str(x.get("result", "")).startswith("made")
                      and trip_times(x)[0] is not None]
        lab_made = [p for p in props if p["label"] == "made"]
        out["made_label_in_reviewed_made_trip"] = sum(any(a - 1 <= p["t"] <= b + 2 for a, b in made_trips)
                                                      for p in lab_made)
    return out


def main(argv=None):
    from .coach_features import attack_sides
    ap = argparse.ArgumentParser(prog="hoop-tape-miner shot-proposals", description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="run folder with rim_scan.pkl (and possessions.pkl)")
    ap.add_argument("--scan", help="default: RUN/rim_scan.pkl")
    ap.add_argument("--official", help="official.json (default: RUN/official.json if present; else unlabelled)")
    ap.add_argument("--review", help="review folder with coach_part*.json, to score the proposals")
    ap.add_argument("--out", help="default: RUN/shot_proposals.json")
    a = ap.parse_args(argv)
    run = Path(a.run)
    scan = pd.read_pickle(Path(a.scan) if a.scan else run / "rim_scan.pkl")
    props = propose(scan)
    poss = pd.read_pickle(run / "possessions.pkl") if (run / "possessions.pkl").exists() else None
    sides = attack_sides(poss) if poss is not None and not poss.empty else {}
    for p in props:
        p["team"] = attack_team(p["t"], p["side"], poss, sides)
    off_path = Path(a.official) if a.official else run / "official.json"
    flow = json.loads(off_path.read_text(encoding="utf-8")).get("score_flow", []) if off_path.is_file() else None
    if flow is None:
        for p in props:
            p.update(label="unlabelled", points=None, official_t=None)
        unmatched, flow = [], []
    else:
        props, unmatched = label(props, flow)
    trips = None
    if a.review:
        from .coach_eval import load_trips
        trips = load_trips(Path(a.review))
    ev = evaluate(props, unmatched, flow, trips)
    out = Path(a.out) if a.out else run / "shot_proposals.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {"proposals": props, "evaluation": ev,
           "official_unmatched": [{k: e.get(k) for k in ("our_video_t", "team", "points")} for e in unmatched]}
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"shot-proposals: {len(props)} -> {out}")
    print("evaluation:", json.dumps(ev))


if __name__ == "__main__":
    main()
