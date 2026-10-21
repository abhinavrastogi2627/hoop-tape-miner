"""Personal training sessions: shared helpers for the train-* stages (paths, pose geometry, rep detection,
aggregation, targets, progress). Not a stage itself.

A session is one solo workout filmed on a phone (shooting, finishing, dribbling):

    <workspace>/players/<player>/training/<YYYY-MM-DD>[-n]/   session.json, README*.md, figures, summary.json, plan.json
    <media_root>/players/<player>/training/<date>[-n]/         session.mp4, run/   (heavy; the session folder when no media_root)

Times are seconds of the joined session video (`session.mp4`), written mm:ss.s in reviews and reports.
Pose follows COCO-17 keypoints; image y grows downwards. Lengths are in torso lengths (shoulder centre to hip
centre), so they do not depend on how far the camera stood; angles are 2D and only comparable between sessions
filmed from a similar spot.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from . import timefmt, workspace

# COCO-17 keypoint indices
NOSE, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP, L_KN, R_KN, L_AN, R_AN = 0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16

ZONES = ("ft", "rim", "paint", "mid", "three")
RESULTS = ("make", "miss", "unclear")
CATEGORIES = ("shot", "finish")

# rep detection (see find_reps)
LIFT_MIN = 0.75      # highest wrist at least this many torso lengths above the shoulders
REP_GAP_S = 1.2      # two candidates at least this far apart
DIP_WINDOW_S = 1.2   # look back this long for the dip (lowest knee angle) and the travel
FINISH_TRAVEL = 1.2  # hips moved more than this (torso lengths) before the peak -> finish hint
KP_MIN = 0.3         # keypoint confidence below this counts as missing


# ---- paths -------------------------------------------------------------------------------------------------

def sessions_root(player: str) -> Path:
    return workspace.root() / "players" / str(player) / "training"


def media_root_for(player: str, prof: dict | None = None) -> Path:
    media_root = (workspace.profile() if prof is None else prof).get("media_root")
    if media_root:
        return Path(media_root).expanduser() / "players" / str(player) / "training"
    return sessions_root(player)


def session_name(player: str, date: str) -> str:
    """'2026-10-20', or '2026-10-20-2' when that day already has a session."""
    root = sessions_root(player)
    name, n = date, 2
    while (root / name / "session.json").exists():
        name, n = f"{date}-{n}", n + 1
    return name


def is_session(folder: Path) -> bool:
    return (Path(folder) / "session.json").exists()


def load_session(folder: Path) -> dict:
    return json.loads((Path(folder) / "session.json").read_text(encoding="utf8"))


def session_path(folder: Path, s: dict, key: str, default: str) -> Path:
    """session.json path value (absolute, or relative to the session folder), else folder/default."""
    v = s.get(key)
    p = Path(v).expanduser() if v else Path(default)
    return p if p.is_absolute() else Path(folder) / p


def earlier_sessions(folder: Path) -> list[Path]:
    """Sibling session folders that sort before this one (same player), oldest first."""
    from .movement import earlier_folders
    return earlier_folders(folder, is_session)


# ---- time --------------------------------------------------------------------------------------------------

def mmss(t: float) -> str:
    """83.44 -> '01:23.4' (rounded first: 59.97 -> '01:00.0', not '00:60.0')."""
    return timefmt.mmss(t, 1)


seconds = timefmt.seconds  # '01:23.4' / '1:23' / '1:02:03' / 83.4 -> seconds


# ---- pose geometry -----------------------------------------------------------------------------------------

def angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Angle at b (degrees) of the a-b-c joint; arrays (..., 2); NaN where any point is NaN."""
    u, v = a - b, c - b
    cos = (u * v).sum(-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1) + 1e-9)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def masked(kp: np.ndarray, conf: np.ndarray, thr: float = KP_MIN) -> np.ndarray:
    """(N, 17, 2) keypoints with low-confidence points set to NaN."""
    kp = kp.astype(float).copy()
    kp[conf < thr] = np.nan
    return kp


def _mid(kp, i, j):
    return np.nanmean(np.stack([kp[:, i], kp[:, j]]), axis=0)


def rolling_nanmedian(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    h = max(k // 2, 1)
    for i in range(len(x)):
        w = x[max(0, i - h):i + h + 1]
        if np.isfinite(w).any():
            out[i] = np.nanmedian(w)
    return out


def body_series(t: np.ndarray, kp: np.ndarray) -> dict:
    """Per-frame body signals from masked keypoints (N, 17, 2)."""
    fps = 1 / np.median(np.diff(t)) if len(t) > 1 else 15.0
    with np.errstate(all="ignore"):
        sh, hip = _mid(kp, L_SH, R_SH), _mid(kp, L_HIP, R_HIP)
        torso = rolling_nanmedian(np.linalg.norm(sh - hip, axis=1), int(fps * 2) | 1)
        wy = kp[:, [L_WR, R_WR], 1]                       # wrist heights (y down)
        lift_lr = (sh[:, 1:2] - wy) / torso[:, None]       # torso lengths above the shoulders, per wrist
        lift = np.nanmax(np.where(np.isfinite(lift_lr), lift_lr, -np.inf), axis=1)
        lift[~np.isfinite(lift)] = np.nan
        knee = np.nanmean(np.stack([angle(kp[:, L_HIP], kp[:, L_KN], kp[:, L_AN]),
                                    angle(kp[:, R_HIP], kp[:, R_KN], kp[:, R_AN])]), axis=0)
        elbow = np.stack([angle(kp[:, L_SH], kp[:, L_EL], kp[:, L_WR]), angle(kp[:, R_SH], kp[:, R_EL], kp[:, R_WR])], 1)
    return dict(t=t, fps=fps, sh=sh, hip=hip, torso=torso, lift=lift, lift_lr=lift_lr, knee=knee, elbow=elbow)


def _peaks(x: np.ndarray, thr: float, gap: int) -> list[int]:
    """Indices of local maxima >= thr, at least `gap` samples apart (greedy, highest first)."""
    idx = [i for i in range(len(x)) if np.isfinite(x[i]) and x[i] >= thr
           and x[i] >= np.nanmax(x[max(0, i - gap // 2):i + gap // 2 + 1])]
    chosen: list[int] = []
    for i in sorted(idx, key=lambda i: -x[i]):
        if all(abs(i - j) >= gap for j in chosen):
            chosen.append(i)
    return sorted(chosen)


def _r(v, nd=2):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def find_reps(t: np.ndarray, kp: np.ndarray, conf: np.ndarray | None = None) -> list[dict]:
    """Shot / finish candidates: peaks of the highest wrist above the shoulders, with form metrics.

    Each candidate: id, t (release = wrist peak), hint (shot | finish), hand (R | L, the higher wrist), two_hands,
    lift (release height, torso lengths above the shoulders), knee_bend (180 - lowest knee angle in the dip, deg),
    dip_to_release (s), elbow_set (elbow angle when the wrist first passes 0.3 above the shoulders, deg),
    elbow_release (deg), jump (hip rise, torso lengths), travel (hip movement before the peak, torso lengths),
    pose_conf. Missing metrics are None. Detection favours recall: the film review rejects false candidates."""
    kp = masked(kp, conf) if conf is not None else kp.astype(float)
    b = body_series(t, kp)
    fps, lift = b["fps"], b["lift"]
    reps = []
    for n, i in enumerate(_peaks(lift, LIFT_MIN, max(int(REP_GAP_S * fps), 1)), 1):
        lo = max(0, i - int(DIP_WINDOW_S * fps))
        torso = b["torso"][i]
        lr = b["lift_lr"][i]
        hand = "L" if np.nan_to_num(lr[0], nan=-9) > np.nan_to_num(lr[1], nan=-9) else "R"
        arm = 0 if hand == "L" else 1
        knee = b["knee"][lo:i + 1]
        dip = lo + int(np.nanargmin(knee)) if np.isfinite(knee).any() else None
        after = range(dip if dip is not None else lo, i + 1)
        set_i = next((j for j in after if np.isfinite(b["lift_lr"][j, arm]) and b["lift_lr"][j, arm] >= 0.3), None)
        base = b["hip"][max(0, i - int(2 * fps)):max(1, i - int(0.8 * fps)), 1]
        near = b["hip"][max(0, i - int(0.3 * fps)):i + int(0.3 * fps) + 1, 1]
        with np.errstate(all="ignore"):
            jump = (np.nanmedian(base) - np.nanmin(near)) / torso if np.isfinite(base).any() and np.isfinite(near).any() else np.nan
            travel = abs(b["hip"][i, 0] - b["hip"][lo, 0]) / torso
        rep = dict(id=f"R{n:03d}", t=round(float(t[i]), 2), hint="finish" if np.nan_to_num(travel) > FINISH_TRAVEL else "shot",
                   hand=hand, two_hands=bool(np.all(np.nan_to_num(lr, nan=-9) >= 0.4)), lift=_r(lift[i]),
                   knee_bend=_r(180 - knee[dip - lo], 1) if dip is not None else None,
                   dip_to_release=_r(t[i] - t[dip]) if dip is not None else None,
                   elbow_set=_r(b["elbow"][set_i, arm], 1) if set_i is not None else None,
                   elbow_release=_r(b["elbow"][i, arm], 1), jump=_r(jump), travel=_r(travel),
                   pose_conf=_r(float(np.nanmean(conf[i])) if conf is not None else np.nan))
        reps.append(rep)
    return reps


def find_dribbles(t: np.ndarray, kp: np.ndarray, conf: np.ndarray | None = None, ball: np.ndarray | None = None,
                  prominence: float = 0.12, max_gap_s: float = 0.9, min_bounces: int = 4,
                  min_unseen_bounces: int = 8) -> list[dict]:
    """Dribble segments from rhythmic wrist up-down below the shoulders (pose), optionally checked against the ball.

    ball: (N, 2) ball centre per frame or NaN. A bounce = a local low point of the wrist (y max) with the given
    prominence (torso lengths); bounces closer than max_gap_s join into one segment; both hands merge into one
    block. Each block: from, to, bounces {R, L}, rate (bounces/s), ball_seen (share of bounces with the ball
    within 1.5 torso lengths of the hand; None without ball data). With ball data, a block where the ball was
    never seen needs min_unseen_bounces bounces (short ball-less blocks are mostly running or arm swing)."""
    from scipy.signal import find_peaks
    kp = masked(kp, conf) if conf is not None else kp.astype(float)
    b = body_series(t, kp)
    fps = b["fps"]
    events = []  # (time, hand, frame)
    for hand, wr in (("L", L_WR), ("R", R_WR)):
        y = kp[:, wr, 1]
        ok = np.isfinite(y) & np.isfinite(b["torso"]) & (y > b["sh"][:, 1])  # below the shoulders
        rel = np.where(ok, (y - rolling_nanmedian(np.where(ok, y, np.nan), int(fps * 0.8) | 1)) / b["torso"], np.nan)
        sig = np.nan_to_num(rel, nan=0.0)
        pk, _ = find_peaks(sig, prominence=prominence, distance=max(int(0.18 * fps), 1))
        events += [(float(t[p]), hand, int(p)) for p in pk if ok[p]]
    events.sort()
    blocks, cur = [], []
    for e in events:
        if cur and e[0] - cur[-1][0] > max_gap_s:
            blocks.append(cur)
            cur = []
        cur.append(e)
    if cur:
        blocks.append(cur)
    out = []
    for blk in blocks:
        if len(blk) < min_bounces:
            continue
        t0, t1 = blk[0][0], blk[-1][0]
        seen = None
        if ball is not None:
            hits = [np.isfinite(ball[f]).all() and np.linalg.norm(ball[f] - kp[f, L_WR if h == "L" else R_WR]) < 1.5 * b["torso"][f]
                    for _, h, f in blk]
            seen = round(float(np.mean(hits)), 2)
            if seen == 0 and len(blk) < min_unseen_bounces:
                continue
        out.append(dict(**{"from": round(t0, 2), "to": round(t1, 2)},
                        bounces={"R": sum(h == "R" for _, h, _ in blk), "L": sum(h == "L" for _, h, _ in blk)},
                        rate=round(len(blk) / max(t1 - t0, 1e-6), 2), ball_seen=seen))
    return out


def pick_main(frames: list[np.ndarray], seed: tuple[float, float] | None = None, size: tuple[int, int] | None = None) -> list[int | None]:
    """Index of the main person in each frame's (M, 4) xyxy boxes: start from the largest person (or the one
    nearest `seed`, x/y fractions of the frame), then follow the box nearest the previous one; fall back to the
    largest person when the previous one is lost for long."""
    out: list[int | None] = []
    prev, lost = None, 0
    for boxes in frames:
        if boxes is None or len(boxes) == 0:
            out.append(None)
            lost += 1
            continue
        c = np.c_[(boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2]
        h = boxes[:, 3] - boxes[:, 1]
        area = (boxes[:, 2] - boxes[:, 0]) * h
        if prev is None or lost > 30:
            if prev is None and seed is not None and size is not None:
                k = int(np.argmin(np.linalg.norm(c - np.array([seed[0] * size[0], seed[1] * size[1]]), axis=1)))
            else:
                k = int(np.argmax(area))
        else:
            d = np.linalg.norm(c - prev[0], axis=1) / max(prev[1], 1.0)
            k = int(np.argmin(d))
            if d[k] > 1.5:  # nobody near the last position: the main player left the frame or was missed
                out.append(None)
                lost += 1
                continue
        prev, lost = (c[k], h[k]), 0
        out.append(k)
    return out


HOLD_R = 0.25  # ball centre within this many body heights of a wrist = that person holds the ball


def ball_holder(boxes: np.ndarray, kp: np.ndarray, cf: np.ndarray, bl: np.ndarray | None) -> int | None:
    """Index of the one person with a wrist within HOLD_R body heights of a ball centre (nobody else as close)."""
    if bl is None or not len(bl) or not len(boxes):
        return None
    h = boxes[:, 3] - boxes[:, 1]
    d = np.full(len(boxes), np.inf)
    for k in range(len(boxes)):
        w = kp[k, [L_WR, R_WR]][cf[k, [L_WR, R_WR]] >= KP_MIN]
        if len(w):
            d[k] = np.min(np.linalg.norm(w[:, None] - bl[None], axis=2)) / max(h[k], 1.0)
    order = np.argsort(d)
    if d[order[0]] < HOLD_R and (len(d) == 1 or d[order[1]] >= HOLD_R):
        return int(order[0])
    return None


def pick_ball_carrier(frames: list[np.ndarray], kps: list[np.ndarray], confs: list[np.ndarray],
                      balls: list[np.ndarray], seed: tuple[float, float] | None = None,
                      size: tuple[int, int] | None = None) -> list[int | None]:
    """pick_main for sessions with a trainer or partner in frame: follow whoever holds the ball. Per frame
    (M, 4) boxes, (M, 17, 2) keypoints, (M, 17) confidences and (B, 2) ball centres. When a ball is seen within
    HOLD_R body heights of someone's wrist (and nobody else is as close), the pick moves to that person; otherwise
    it follows the box nearest the previous pick, as pick_main does. Shots, finishes and dribbles are all made by
    the ball carrier, so the shooter is picked from the set point on; the film review rejects the partner's reps."""
    out: list[int | None] = []
    prev, lost = None, 0
    for boxes, kp, cf, bl in zip(frames, kps, confs, balls):
        if boxes is None or len(boxes) == 0:
            out.append(None)
            lost += 1
            continue
        c = np.c_[(boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2]
        h = boxes[:, 3] - boxes[:, 1]
        holder = ball_holder(boxes, kp, cf, bl)
        if holder is not None:
            k = holder
        elif prev is None or lost > 30:
            if prev is None and seed is not None and size is not None:
                k = int(np.argmin(np.linalg.norm(c - np.array([seed[0] * size[0], seed[1] * size[1]]), axis=1)))
            else:
                k = int(np.argmax((boxes[:, 2] - boxes[:, 0]) * h))
        else:
            d = np.linalg.norm(c - prev[0], axis=1) / max(prev[1], 1.0)
            k = int(np.argmin(d))
            if d[k] > 1.5:
                out.append(None)
                lost += 1
                continue
        prev, lost = (c[k], h[k]), 0
        out.append(k)
    return out


# ---- review aggregation ------------------------------------------------------------------------------------

def reviewed_reps(review: list[dict]) -> list[dict]:
    """Reps from all review parts: real reps only (category shot/finish), sorted by time, with t in seconds."""
    reps = []
    for part in review:
        for r in part.get("reps", []) + part.get("added_reps", []):
            if r.get("category") in CATEGORIES:
                reps.append({**r, "t_s": seconds(r["t"])})
    return sorted(reps, key=lambda r: r["t_s"])


def tally(reps: list[dict]) -> dict:
    """made / att / pct over reps with a decided result (unclear ones counted apart)."""
    made = sum(r.get("result") == "make" for r in reps)
    att = sum(r.get("result") in ("make", "miss") for r in reps)
    return dict(made=made, att=att, pct=round(made / att, 3) if att else None,
                unclear=sum(r.get("result") not in ("make", "miss") for r in reps))


def by(reps: list[dict], key: str, order: tuple = ()) -> dict:
    groups: dict = {}
    for r in reps:
        groups.setdefault(str(r.get(key) or "?"), []).append(r)
    keys = [k for k in order if k in groups] + sorted(k for k in groups if k not in order)
    return {k: tally(groups[k]) for k in keys}


def longest_streak(reps: list[dict]) -> int:
    best = cur = 0
    for r in reps:
        if r.get("result") == "make":
            cur += 1
            best = max(best, cur)
        elif r.get("result") == "miss":
            cur = 0
    return best


def thirds(reps: list[dict], t0: float, t1: float) -> list[dict]:
    """tally per third of the session time (fatigue / warm-up effects)."""
    edges = np.linspace(t0, t1, 4)
    return [tally([r for r in reps if edges[i] <= r["t_s"] < edges[i + 1] + (i == 2)]) for i in range(3)]


def matches(rep: dict, match: dict) -> bool:
    return all(str(rep.get(k, "")).strip().lower() == str(v).strip().lower() for k, v in (match or {}).items())


def check_targets(targets: list[dict], reps: list[dict]) -> list[dict]:
    """Each target {name, match, attempts?, pct?} -> actual numbers and status met | missed | not_trained."""
    out = []
    for tg in targets or []:
        got = tally([r for r in reps if matches(r, tg.get("match", {}))])
        if not got["att"] and not got["unclear"]:
            status = "not_trained"
        else:
            ok_att = got["att"] >= tg.get("attempts", 0)
            ok_pct = tg.get("pct") is None or (got["pct"] is not None and got["pct"] >= tg["pct"])
            status = "met" if ok_att and ok_pct else "missed"
        out.append(dict(name=tg.get("name", json.dumps(tg.get("match", {}), ensure_ascii=False)), match=tg.get("match", {}),
                        attempts=tg.get("attempts"), pct=tg.get("pct"), actual_att=got["att"], actual_made=got["made"],
                        actual_pct=got["pct"], status=status))
    return out


FORM_KEYS = ("lift", "knee_bend", "dip_to_release", "elbow_set", "elbow_release", "jump")


SD_MIN_N = 3  # a spread (consistency) of fewer reps says nothing


def form_stats(reps: list[dict]) -> dict:
    """Per form metric over reps that have it: mean, sample sd (consistency; None below SD_MIN_N reps), n, mean for
    makes and for misses."""
    out = {}
    for k in FORM_KEYS:
        def vals(rs):
            return np.array([r[k] for r in rs if isinstance(r.get(k), (int, float))], float)
        allv = vals(reps)
        if not len(allv):
            continue
        mk, ms = vals([r for r in reps if r.get("result") == "make"]), vals([r for r in reps if r.get("result") == "miss"])
        out[k] = dict(mean=_r(allv.mean()), sd=_r(allv.std(ddof=1)) if len(allv) >= SD_MIN_N else None, n=len(allv),
                      make_mean=_r(mk.mean()) if len(mk) else None, miss_mean=_r(ms.mean()) if len(ms) else None)
    return out
