"""Track features per review trip (numbers back, spacing, paint crowd, ...) and ball-track quality.

usage: hoop-tape-miner coach-features --run <run> --review <run>/review_v1 [--out features.json] [--back-offset 2]
Reads <run>/tracks.pkl, detections.pkl, possessions.pkl and the review's coach_part*.json trips. Writes
<review>/features.json (one entry per trip, keyed "<pid>-<trip>") and <review>/ball_quality.json (ball detection
coverage before and after clean_ball). Unknown values are null, never 0.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .coach_eval import load_trips, trip_times
from .court import LENGTH
from .metrics import hull_area, mean_nn, zone_of

MIN_PLAYERS = 3  # a team with fewer tracked players in a frame says nothing about its shape
MIN_FRAMES = 5  # frames (0.5 s at 10 fps) with enough players before an offence feature is reported
BACK_OFFSET = 2.0  # seconds after t0 for numbers_back (see docs in trip_features)


def _attack_x(x, side):
    """Distance from the far baseline toward the attacked basket: > LENGTH/2 means front court."""
    return x if side == "right" else LENGTH - x


def _r(v, n=2):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)


def trip_features(tracks: pd.DataFrame, trip: dict, attack_side: str, back_offset: float = BACK_OFFSET) -> dict:
    """Court-space features of one trip from smoothed tracks (cx_s, cy_s in metres), window [t0, t1].

    attack_side is the basket the trip's offence attacks ("left" = x 0, "right" = x 28); the defence's own half is
    that half. Definitions:
    - numbers_back_2s: defenders in their own half at t0 + back_offset (median over frames within +-0.25 s that
      have >= 3 tracked defenders), capped at 5. Only tracked defenders count (lower bound when one is off-camera).
      2 s was the best fixed offset against reviewer counts on the reference game (within-1 agreement 0.71).
    - off_spacing_m: mean over frames of the offence's mean nearest-neighbour distance (metres).
    - off_hull_m2: mean convex-hull area of the offence (m^2).
    - paint_crowd: mean number of offence players in the attacked paint per frame.
    - standstill_share: share of offence player-samples (0.1 s steps along a track) moving under 0.5 m/s.
    - cross_half_s: seconds from t0 until >= 4 attackers (all, if only 3 are tracked) are in the front court;
      0 when already there, null when it never happens in the window.
    - off_tracked / def_tracked: median tracked players per frame (context for the numbers above).
    Offence features use only frames with >= 3 tracked attackers and are null when fewer than 5 such frames exist;
    numbers_back_2s is null without >= 3 tracked defenders at that moment (null = unknown, never 0).
    """
    t0, t1 = trip_times(trip)
    off = trip.get("offence")
    dfn = {"us": "them", "them": "us"}.get(off)
    out = dict.fromkeys(("numbers_back_2s", "off_spacing_m", "off_hull_m2", "paint_crowd", "standstill_share",
                         "cross_half_s", "off_tracked", "def_tracked"))
    if t0 is None or dfn is None or attack_side not in ("left", "right"):
        return out
    w = tracks[tracks.team.isin(["us", "them"]) & tracks.t.between(t0 - 0.3, max(t1, t0 + back_offset) + 0.3)]
    w = w.drop_duplicates(["frame", "track"])
    in_trip = w[w.t.between(t0, t1)]
    cnt = in_trip.groupby(["frame", "team"]).size().unstack(fill_value=0).reindex(columns=["us", "them"], fill_value=0)
    if len(cnt):
        out["off_tracked"], out["def_tracked"] = _r(cnt[off].median(), 1), _r(cnt[dfn].median(), 1)

    # numbers back
    d = w[(w.team == dfn) & w.t.between(t0 + back_offset - 0.25, t0 + back_offset + 0.25)]
    back = [int((_attack_x(g.cx_s, attack_side) > LENGTH / 2).sum()) for _, g in d.groupby("frame")
            if len(g) >= MIN_PLAYERS]
    if back:
        out["numbers_back_2s"] = min(5, int(round(float(np.median(back)))))  # >5 = tracking duplicates

    # offence shape
    o = in_trip[in_trip.team == off]
    good = [g for _, g in o.groupby("frame") if len(g) >= MIN_PLAYERS]
    if len(good) < MIN_FRAMES:
        return out
    spac, hull, paint, cross = [], [], [], None
    for g in good:
        p = g[["cx_s", "cy_s"]].to_numpy()
        spac.append(mean_nn(p))
        hull.append(hull_area(p))
        paint.append(sum(zone_of(x, y, attack_side) == "paint" for x, y in p))
        front = int((_attack_x(p[:, 0], attack_side) > LENGTH / 2).sum())
        if cross is None and front >= min(4, len(p)):
            cross = max(0.0, g.t.iloc[0] - t0)
    hull = [h for h in hull if np.isfinite(h)]  # collinear players have no hull
    out.update(off_spacing_m=_r(np.nanmean(spac)), off_hull_m2=_r(np.mean(hull), 1) if hull else None,
               paint_crowd=_r(np.mean(paint)), cross_half_s=_r(cross, 1))
    ok_frames = {g.frame.iloc[0] for g in good}
    s = o[o.frame.isin(ok_frames)].sort_values(["track", "frame"])
    step = s.groupby("track")[["cx_s", "cy_s"]].diff()
    dt = s.groupby("track").t.diff()
    v = (np.hypot(step.cx_s, step.cy_s) / dt)[(dt > 0) & (dt < 0.25)]
    out["standstill_share"] = _r((v < 0.5).mean()) if len(v) else None
    return out


# --- ball -----------------------------------------------------------------------------------------------------

def _ball_rows(dets: pd.DataFrame, conf: float) -> pd.DataFrame:
    b = dets[dets.kind == "ball"] if "kind" in dets else dets
    keep = b.conf >= conf
    if "interp" in b:
        keep |= b.interp.astype(bool)
    return b[keep]


def ball_quality(dets: pd.DataFrame, conf: float = 0.3, frames=None) -> dict:
    """Ball detection quality over the sampled frames (all frames in dets, or the given frame list).

    coverage: share of frames with >= 1 ball (conf >= conf, or interpolated); multi_share: share of those frames
    with >= 2 balls; gap_p50 / gap_p90: percentiles of the time between consecutive ball frames (s; 0.1 = no gap).
    """
    n = len(set(frames)) if frames is not None else dets.frame.nunique()
    b = _ball_rows(dets, conf)
    per = b.groupby("frame").size()
    ts = np.sort(b.groupby("frame").t.first().to_numpy())
    gaps = np.diff(ts)
    return {"frames": int(n), "ball_frames": int(len(per)),
            "coverage": round(len(per) / n, 3) if n else None,
            "multi_share": round(float((per >= 2).mean()), 3) if len(per) else None,
            "gap_p50": round(float(np.percentile(gaps, 50)), 2) if len(gaps) else None,
            "gap_p90": round(float(np.percentile(gaps, 90)), 2) if len(gaps) else None}


def project_balls(dets: pd.DataFrame, cam: dict) -> pd.DataFrame:
    """Fill ball cx, cy (court metres) from the box bottom-centre with camera.npz (H maps court -> image per frame).

    extract leaves them NaN. For a ball in the air the point lands beyond its true spot; clean_ball only uses it to
    find objects that stay put on the court (bags, bins, spare balls).
    """
    d = dets.copy()
    pos = {int(f): i for i, f in enumerate(cam["frame"])}
    m = (d.kind == "ball").to_numpy() & d.frame.map(pos).notna().to_numpy()
    H = np.asarray(cam["H"], float)[d.frame[m].map(pos).astype(int).to_numpy()]
    ok = np.isfinite(H).all(axis=(1, 2))
    Hinv = np.full_like(H, np.nan)
    Hinv[ok] = np.linalg.inv(H[ok])
    foot = np.c_[(d.x1[m] + d.x2[m]) / 2, d.y2[m], np.ones(m.sum())]
    p = np.einsum("nij,nj->ni", Hinv, foot)
    d.loc[m, "cx"], d.loc[m, "cy"] = p[:, 0] / p[:, 2], p[:, 1] / p[:, 2]
    return d


def clean_ball(dets: pd.DataFrame, min_conf: float = 0.3, max_speed_px: float = 1200.0, slack_px: float = 30.0,
               max_gap: float = 0.5, anchor_conf: float = 0.5, static_s: float = 1.0,
               static_m: float = 0.5) -> pd.DataFrame:
    """One ball per frame, chosen by motion consistency in image space (pixel boxes link; court cx/cy only flag
    world-static objects).

    Candidates (conf >= min_conf) are linked frame to frame into tracklets when the box centre is within
    max_speed_px * dt + slack_px of the tracklet's constant-velocity prediction and dt <= max_gap. A tracklet is
    dropped unless one of its detections has conf >= anchor_conf, and dropped when it lasts >= static_s while its
    ground projection (cx, cy) stays within static_m of its median: bags, bins and spare balls by the bench (the
    camera pans, so they move in the image but not on the court). In each frame the candidate on the surviving
    tracklet with the largest summed confidence wins. Gaps <= max_gap inside one tracklet are linearly
    interpolated (interp=True, conf NaN).
    Returns frame, t, x1, y1, x2, y2, conf, px, py, tracklet, interp.
    """
    allf = np.unique(dets.frame.to_numpy())
    fstep = int(np.min(np.diff(allf))) if len(allf) > 1 else 1
    b = dets[(dets.kind == "ball") & (dets.conf >= min_conf)] if "kind" in dets else dets[dets.conf >= min_conf]
    b = b.sort_values(["frame", "conf"], ascending=[True, False]).reset_index(drop=True)
    cols = ["frame", "t", "x1", "y1", "x2", "y2", "conf", "px", "py", "tracklet", "interp"]
    if b.empty:
        return pd.DataFrame(columns=cols)
    b["px"], b["py"] = (b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2
    tl = np.full(len(b), -1)
    active: dict[int, list] = {}  # id -> [t, x, y, vx, vy]
    nxt = 0
    for f, idx in b.groupby("frame", sort=True).groups.items():
        t = float(b.t[idx[0]])
        active = {k: a for k, a in active.items() if t - a[0] <= max_gap + 1e-6}
        used = set()
        for i in idx:  # by confidence, high first
            best, bd = None, None
            for k, (ta, xa, ya, vx, vy) in active.items():
                if k in used:
                    continue
                dt = t - ta
                d = np.hypot(b.px[i] - (xa + vx * dt), b.py[i] - (ya + vy * dt))
                if d <= max_speed_px * dt + slack_px and (bd is None or d < bd):
                    best, bd = k, d
            if best is None:
                best, nxt = nxt, nxt + 1
                vx = vy = 0.0
            else:
                ta, xa, ya, _, _ = active[best]
                dt = t - ta
                vx, vy = (b.px[i] - xa) / dt, (b.py[i] - ya) / dt
                sp = np.hypot(vx, vy)
                if sp > max_speed_px:
                    vx, vy = vx * max_speed_px / sp, vy * max_speed_px / sp
            active[best] = [t, b.px[i], b.py[i], vx, vy]
            used.add(best)
            tl[i] = best
    b["tracklet"] = tl
    g = b.groupby("tracklet")
    keep = g.conf.max() >= anchor_conf
    if {"cx", "cy"} <= set(b.columns):
        spread = g.apply(lambda d: float(np.hypot(d.cx - d.cx.median(), d.cy - d.cy.median()).max()))
        keep &= ~(((g.t.max() - g.t.min()) >= static_s) & (spread < static_m))
    b = b[b.tracklet.map(keep)].copy()
    b["score"] = b.tracklet.map(b.groupby("tracklet").conf.sum())
    pick = b.sort_values(["frame", "score", "conf"], ascending=[True, False, False]).drop_duplicates("frame")
    pick = pick.assign(interp=False)[cols]
    fill = []
    for (_, a), (_, c) in zip(pick.iloc[:-1].iterrows(), pick.iloc[1:].iterrows()):
        if a.tracklet != c.tracklet or c.t - a.t > max_gap + 1e-6 or c.frame - a.frame <= fstep:
            continue
        for f in range(int(a.frame) + fstep, int(c.frame), fstep):
            u = (f - a.frame) / (c.frame - a.frame)
            row = {k: a[k] + u * (c[k] - a[k]) for k in ("t", "x1", "y1", "x2", "y2", "px", "py")}
            fill.append(dict(row, frame=f, conf=np.nan, tracklet=a.tracklet, interp=True))
    out = pd.concat([pick, pd.DataFrame(fill, columns=cols)]) if fill else pick
    out = out.astype({"frame": int, "interp": bool})
    return out.sort_values("frame").reset_index(drop=True)


def ball_holder(ball: pd.DataFrame, tracks: pd.DataFrame, reach: float = 0.5) -> pd.DataFrame:
    """Per clean-ball frame, the player whose image box holds the ball (us/them only), else NaN.

    A box qualifies when the ball centre lies within the box widened by reach * box width on each side and between
    the box top (minus 20 % of its height) and its bottom; the nearest qualifying box (horizontal offset outside the
    box) wins. A ball in the air or on the floor between players gets no holder.
    """
    p = tracks[tracks.team.isin(["us", "them"])]
    by_f = {f: g for f, g in p.groupby("frame")}
    rows = []
    for r in ball.itertuples():
        g = by_f.get(r.frame)
        team = track = np.nan
        if g is not None:
            w, h = g.x2 - g.x1, g.y2 - g.y1
            px, py = (r.x1 + r.x2) / 2, (r.y1 + r.y2) / 2
            ok = (px >= g.x1 - reach * w) & (px <= g.x2 + reach * w) & (py >= g.y1 - 0.2 * h) & (py <= g.y2)
            if ok.any():
                dx = np.maximum(0, np.maximum(g.x1 - px, px - g.x2))
                best = dx[ok].idxmin()
                team, track = g.team[best], g.track[best]
        rows.append(dict(frame=r.frame, t=r.t, team=team, track=track, interp=r.interp))
    return pd.DataFrame(rows, columns=["frame", "t", "team", "track", "interp"])


# --- CLI ------------------------------------------------------------------------------------------------------

def attack_sides(poss: pd.DataFrame) -> dict:
    """{(period, team): side attacked}: majority of the possessions' (side, offence) per period."""
    m = {}
    for (per, off), g in poss.groupby(["period", "offence"]):
        m[(per, off)] = Counter(g.side).most_common(1)[0][0]
    for per in poss.period.unique():  # fill a missing team with the other basket
        for a, b in (("us", "them"), ("them", "us")):
            if (per, a) not in m and (per, b) in m:
                m[(per, a)] = "left" if m[(per, b)] == "right" else "right"
    return m


def trip_attack_side(trip: dict, poss: pd.DataFrame, sides: dict) -> str | None:
    """Attack side for a trip: the (period, offence) direction; the period comes from its pid (or nearest start)."""
    pid = trip.get("pid")
    if pid in poss.index:
        per = poss.loc[pid, "period"]
    else:
        t0 = trip_times(trip)[0]
        if t0 is None or poss.empty:
            return None
        per = poss.period[(poss.start - t0).abs().idxmin()]
    return sides.get((per, trip.get("offence")))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-features")
    ap.add_argument("--run", required=True, help="run folder with tracks.pkl, detections.pkl, possessions.pkl")
    ap.add_argument("--review", required=True, help="review folder with coach_part*.json")
    ap.add_argument("--out", help="default: <review>/features.json")
    ap.add_argument("--back-offset", type=float, default=BACK_OFFSET, help="seconds after t0 for numbers_back")
    a = ap.parse_args(argv)
    run, review = Path(a.run), Path(a.review)
    tracks = pd.read_pickle(run / "tracks.pkl")
    poss = pd.read_pickle(run / "possessions.pkl")
    sides = attack_sides(poss)
    feats = {}
    for x in load_trips(review):
        side = trip_attack_side(x, poss, sides)
        t0, t1 = trip_times(x)
        f = trip_features(tracks, x, side, back_offset=a.back_offset) if side else {}
        feats[f"{x.get('pid')}-{x.get('trip', 1)}"] = dict(pid=x.get("pid"), trip=x.get("trip", 1),
                                                           offence=x.get("offence"), attack_side=side,
                                                           t0=t0, t1=t1, **f)
    out = Path(a.out) if a.out else review / "features.json"
    out.write_text(json.dumps(feats, ensure_ascii=False, indent=1), encoding="utf8")
    dets = pd.read_pickle(run / "detections.pkl")
    if (run / "camera.npz").exists():
        dets = project_balls(dets, dict(np.load(run / "camera.npz")))
    frames = dets.frame.unique()
    clean = clean_ball(dets)
    q = {"raw": ball_quality(dets, 0.3), "raw_conf05": ball_quality(dets, 0.5),
         "clean": ball_quality(clean, 0.3, frames=frames),
         "clean_detected_only": ball_quality(clean[~clean.interp], 0.3, frames=frames)}
    (review / "ball_quality.json").write_text(json.dumps(q, indent=1), encoding="utf8")
    n = sum(v.get("numbers_back_2s") is not None for v in feats.values())
    print(f"features: {len(feats)} trips ({n} with numbers_back) -> {out}")
    print("ball quality:", json.dumps(q))


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
