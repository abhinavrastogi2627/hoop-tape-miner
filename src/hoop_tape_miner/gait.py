"""2D running, layup and dribble metrics from one player's pose track (pure functions, no video).

Input everywhere: t (N,) source seconds, kp (N,17,2) COCO keypoints in px, conf (N,17). Image y grows downward.
Signed metrics follow the running direction (direction()), so a player running right-to-left gets the same signs.
Lengths are in leg lengths (leg_length()). Missing = None, never 0. Contact times only at >= 100 fps: below that
one frame is too coarse (spec: docs/superpowers/specs/2026-10-20-movement-lab-design.md).
"""
from __future__ import annotations

import math

import numpy as np

from . import training as T

METRICS_VERSION = 1
CONTACT_FPS_MIN = 100.0
STEP_KEYS = ("trunk_lean", "shin", "touchdown_ahead", "knee_lift", "heel_recovery", "step_len", "step_time", "contact_s")
FEET = {"L": (T.L_AN, T.L_KN, T.L_HIP), "R": (T.R_AN, T.R_KN, T.R_HIP)}
SPEED_SHARE = 0.25   # stance ankle moves slower than this share of the hip's speed (our rule)
SPEED_FLOOR = 0.1    # ... plus this many leg lengths / s of keypoint jitter (our rule)
FLOOR_TOL = 0.06     # and sits within this many leg lengths of the floor line (our rule)
GATE_RECALL, GATE_PRECISION, GATE_MAE_FRAMES = 0.8, 0.8, 1.5  # hand-label check a metric must pass (our rule)


def _fps(t: np.ndarray) -> float:
    """Frame rate from the median gap between distinct timestamps (repeated ones would give inf); 0 when unknown."""
    dt = np.diff(np.asarray(t, float))
    dt = dt[np.isfinite(dt) & (dt > 0)]
    return float(1 / np.median(dt)) if len(dt) else 0.0


def _pair(kp: np.ndarray, i: int, j: int) -> np.ndarray:
    """Mean of two keypoints per frame, or the one that is present."""
    with np.errstate(all="ignore"), _quiet():
        return np.nanmean(np.stack([kp[:, i], kp[:, j]]), axis=0)


class _quiet:
    def __enter__(self):
        import warnings
        self.w = warnings.catch_warnings()
        self.w.__enter__()
        warnings.simplefilter("ignore", RuntimeWarning)

    def __exit__(self, *a):
        self.w.__exit__(*a)


def _floor(kp: np.ndarray, fps: float) -> np.ndarray:
    """Floor line per frame: the lowest ankle (largest y) over the surrounding second."""
    with _quiet():
        low = np.nanmax(kp[:, [T.L_AN, T.R_AN], 1], axis=1)
    h = max(int(round(fps / 2)), 1)
    out = np.full(len(low), np.nan)
    for i in range(len(low)):
        w = low[max(0, i - h):i + h + 1]
        if np.isfinite(w).any():
            out[i] = np.nanmax(w)
    return out


def leg_length(kp: np.ndarray) -> float:
    """Leg length in px: 90th percentile of the hip-to-lower-ankle height (frames with a straight-ish support leg)."""
    with _quiet():
        hip = _pair(kp, T.L_HIP, T.R_HIP)[:, 1]
        low = np.nanmax(kp[:, [T.L_AN, T.R_AN], 1], axis=1)
        d = low - hip
        return float(np.nanpercentile(d, 90)) if np.isfinite(d).any() else float("nan")


def direction(t: np.ndarray, kp: np.ndarray) -> int:
    """+1 = moving to image right, -1 = left, 0 = unknown (hips moved under half a leg length)."""
    hx = _pair(kp, T.L_HIP, T.R_HIP)[:, 0]
    ok = np.flatnonzero(np.isfinite(hx))
    L = leg_length(kp)
    if len(ok) < 2 or not math.isfinite(L):
        return 0
    with _quiet():
        v = np.nanmedian(np.diff(hx[ok]))
    net = hx[ok[-1]] - hx[ok[0]]
    if abs(net) < 0.5 * L or v == 0:
        return 0
    return 1 if v > 0 else -1


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def foot_contacts(t: np.ndarray, kp: np.ndarray, conf: np.ndarray, min_gap_s: float = 0.12) -> list[dict]:
    """Ground contacts per foot, sorted by onset: {"foot", "on", "off", "i_on", "i_off"}. A contact is a run of frames
    where the ankle is near the floor line and nearly still while the hips move. Runs that start the clip or follow
    a missing frame are dropped (onset unknown); "off" is None when the run ends the clip or hits a missing frame."""
    kp = T.masked(kp, conf)
    n = len(t)
    fps = _fps(t)
    L = leg_length(kp)
    if n < 3 or not math.isfinite(L):
        return []
    hx = _pair(kp, T.L_HIP, T.R_HIP)[:, 0]
    hv = np.full(n, np.nan)
    hv[1:-1] = np.abs(hx[2:] - hx[:-2]) * fps / 2
    hip_speed = T.rolling_nanmedian(hv, max(3, int(round(0.3 * fps))))
    hip_speed[~np.isfinite(hx)] = np.nan
    floor = _floor(kp, fps)
    min_len = 2 if fps >= 40 else 1
    out = []
    for foot, (an, _, _) in FEET.items():
        raw_x, ay = kp[:, an, 0], kp[:, an, 1]
        ax = T.rolling_nanmedian(raw_x, 3)
        ax[~np.isfinite(raw_x)] = np.nan
        fwd, bwd = np.full(n, np.nan), np.full(n, np.nan)
        fwd[:-1] = np.abs(np.diff(ax)) * fps
        bwd[1:] = np.abs(np.diff(ax)) * fps
        with _quiet():
            speed = np.fmin(fwd, bwd)
            good = np.isfinite(ax) & np.isfinite(ay) & np.isfinite(hip_speed) & np.isfinite(floor)
            on = good & (speed < SPEED_SHARE * hip_speed + SPEED_FLOOR * L) & (ay >= floor - FLOOR_TOL * L)
        runs = _runs(on)
        merged: list[list[int]] = []
        for a, b in runs:  # close flicker gaps shorter than min_gap_s when every gap frame was seen
            if merged and (a - merged[-1][1] - 1) / fps < min_gap_s and good[merged[-1][1] + 1:a].all():
                merged[-1][1] = b
            else:
                merged.append([a, b])
        for a, b in merged:
            if b - a + 1 < min_len or a == 0 or not good[a - 1]:
                continue
            ends = b == n - 1 or not good[b + 1]
            out.append(dict(foot=foot, on=float(t[a]), off=None if ends else float(t[b]), i_on=int(a),
                            i_off=None if ends else int(b)))
    return sorted(out, key=lambda c: c["on"])


def _deg(dx, dy) -> float | None:
    v = math.degrees(math.atan2(dx, dy))
    return v if math.isfinite(v) else None


def _num(v) -> float | None:
    return float(v) if v is not None and math.isfinite(v) else None


def step_metrics(t: np.ndarray, kp: np.ndarray, conf: np.ndarray, contacts: list[dict]) -> list[dict]:
    """One row per touchdown: trunk_lean (deg, + = forward), shin (deg from vertical, + = knee ahead of ankle),
    touchdown_ahead (leg lengths, + = foot ahead of hip), knee_lift (deg, peak thigh angle in the swing before),
    heel_recovery (peak ankle height in that swing, leg lengths), step_len (leg lengths from the other foot's last
    touchdown), step_time (s), contact_s (s, None below 100 fps). Signed values are None when direction is unknown."""
    kp = T.masked(kp, conf)
    fps, L, d = _fps(t), leg_length(kp), direction(t, kp)
    if not contacts or not math.isfinite(L):
        return []
    hip, sh = _pair(kp, T.L_HIP, T.R_HIP), _pair(kp, T.L_SH, T.R_SH)
    rows = []
    for n, c in enumerate(contacts):
        an, kn, hp = FEET[c["foot"]]
        i = c["i_on"]
        a, k, h, s = kp[i, an], kp[i, kn], hip[i], sh[i]
        row = dict(t=c["on"], foot=c["foot"], trunk_lean=None, shin=None, touchdown_ahead=None, knee_lift=None,
                   heel_recovery=None, step_len=None, step_time=None, contact_s=None)
        if d:
            row["trunk_lean"] = _deg(d * (s[0] - h[0]), h[1] - s[1])
            row["shin"] = _deg(d * (k[0] - a[0]), a[1] - k[1])
            row["touchdown_ahead"] = _num(d * (a[0] - h[0]) / L)
        prev_same = next((p for p in reversed(contacts[:n]) if p["foot"] == c["foot"]), None)
        j0 = (prev_same["i_off"] or prev_same["i_on"]) + 1 if prev_same else max(0, i - int(round(0.6 * fps)))
        if j0 < i:
            sw = slice(j0, i)
            with _quiet():
                if d:
                    thigh = np.degrees(np.arctan2(d * (kp[sw, kn, 0] - hip[sw, 0]), kp[sw, kn, 1] - hip[sw, 1]))
                    row["knee_lift"] = _num(np.nanmax(thigh)) if np.isfinite(thigh).any() else None
                lift = (a[1] - kp[sw, an, 1]) / L
                row["heel_recovery"] = _num(np.nanmax(lift)) if np.isfinite(lift).any() else None
        if n and contacts[n - 1]["foot"] != c["foot"]:
            p = contacts[n - 1]
            pa = kp[p["i_on"], FEET[p["foot"]][0]]
            if d:
                row["step_len"] = _num(d * (a[0] - pa[0]) / L)
            row["step_time"] = c["on"] - p["on"]
        if fps >= CONTACT_FPS_MIN and c["i_off"] is not None:
            row["contact_s"] = (c["i_off"] - c["i_on"] + 1) / fps
        rows.append(row)
    return rows


def _stats(vals: list[float]) -> dict | None:
    if not vals:
        return None
    return dict(mean=float(np.mean(vals)), sd=float(np.std(vals)), first3=float(np.mean(vals[:3])), n=len(vals))


def clip_metrics(steps: list[dict], fps: float) -> dict:
    """Per clip: n_steps, cadence_spm (60 / median step time), and for each STEP_KEYS key {mean, sd, first3, n}
    (first3 = the first three steps, the acceleration) or None."""
    out = dict(n_steps=len(steps), fps=float(fps), contact_ok=fps >= CONTACT_FPS_MIN)
    st = [s["step_time"] for s in steps if s.get("step_time")]
    out["cadence_spm"] = 60 / float(np.median(st)) if st else None
    for k in STEP_KEYS:
        out[k] = _stats([s[k] for s in steps if s.get(k) is not None])
    return out


def layup_metrics(t: np.ndarray, kp: np.ndarray, conf: np.ndarray, contacts: list[dict], release_t: float) -> dict:
    """The approach of one layup (release at release_t): takeoff_t / takeoff_foot (last contact before release),
    last3_len (lengths of the last three steps), penultimate_ratio (step onto the penultimate contact / median
    earlier step), hip_drop (lowest hip from the penultimate touchdown to take-off vs the earlier run-up, leg lengths,
    + = lower), takeoff_knee (smallest knee angle on the take-off contact, deg), takeoff_trunk, takeoff_ahead (at the
    take-off touchdown), free_knee (peak thigh angle of the free leg from take-off touchdown to release, deg from
    vertical, + = forward), landing_knee_min (smallest knee angle in the second after release)."""
    out = dict(takeoff_t=None, takeoff_foot=None, last3_len=[], penultimate_ratio=None, hip_drop=None,
               takeoff_knee=None, takeoff_trunk=None, takeoff_ahead=None, free_knee=None, landing_knee_min=None)
    before = [c for c in contacts if c["on"] <= release_t]
    if not before:
        return out
    steps = step_metrics(t, kp, conf, before)
    km = T.masked(kp, conf)
    L = leg_length(km)
    take, tk = before[-1], steps[-1]
    out["takeoff_foot"] = take["foot"]
    out["takeoff_t"] = take["off"] if take["off"] is not None and take["off"] <= release_t else take["on"]
    out["takeoff_trunk"], out["takeoff_ahead"] = tk["trunk_lean"], tk["touchdown_ahead"]
    out["last3_len"] = [s["step_len"] for s in steps[-3:]]
    an, kn, hp = FEET[take["foot"]]
    i1 = take["i_off"] if take["i_off"] is not None else min(len(t) - 1, int(np.searchsorted(t, release_t)))
    knee = T.angle(km[take["i_on"]:i1 + 1, hp], km[take["i_on"]:i1 + 1, kn], km[take["i_on"]:i1 + 1, an])
    out["takeoff_knee"] = _num(np.nanmin(knee)) if np.isfinite(knee).any() else None
    d = direction(t, km)
    if d:
        _, fk, fh = FEET["R" if take["foot"] == "L" else "L"]
        w = slice(take["i_on"], min(len(t), int(np.searchsorted(t, release_t, side="right"))))
        with _quiet():
            th = np.degrees(np.arctan2(d * (km[w, fk, 0] - km[w, fh, 0]), km[w, fk, 1] - km[w, fh, 1]))
        out["free_knee"] = _num(np.nanmax(th)) if np.isfinite(th).any() else None
    if len(steps) >= 2:
        pen = steps[-2]
        earlier = [s["step_len"] for s in steps[:-2] if s["step_len"] is not None]
        if pen["step_len"] is not None and earlier:
            out["penultimate_ratio"] = _num(pen["step_len"] / float(np.median(earlier)))
        hy = _pair(km, T.L_HIP, T.R_HIP)[:, 1]
        p0, first = before[-2]["i_on"], before[0]["i_on"]
        with _quiet():
            run_up, low = hy[first:p0], hy[p0:take["i_on"] + 1]
            if math.isfinite(L) and np.isfinite(run_up).any() and np.isfinite(low).any():
                out["hip_drop"] = _num((np.nanmax(low) - np.nanmedian(run_up)) / L)
    land = (t > release_t) & (t <= release_t + 1.0)
    if land.any():
        ks = [T.angle(km[land, h], km[land, k], km[land, a]) for a, k, h in FEET.values()]
        allk = np.concatenate(ks)
        out["landing_knee_min"] = _num(np.nanmin(allk)) if np.isfinite(allk).any() else None
    return out


def _extrema(y: np.ndarray, fps: float, L: float, low: bool) -> list[int]:
    """Indices of local maxima of y (low=False) or minima (low=True) standing out by 0.2 leg lengths."""
    s = -y if low else y
    h, w = max(1, int(round(0.15 * fps))), max(2, int(round(0.25 * fps)))
    out = []
    for i in range(h, len(s) - h):  # a peak at the clip edge may not be the real one
        if not math.isfinite(s[i]):
            continue
        win = s[max(0, i - h):i + h + 1]
        wide = s[max(0, i - w):i + w + 1]
        if s[i] >= np.nanmax(win) and s[i] - np.nanmin(wide) > 0.2 * L and (not out or i - out[-1] > h):
            out.append(i)
    return out


def dribble_metrics(t: np.ndarray, kp: np.ndarray, ball: np.ndarray, m_per_px: float | None = None) -> dict:
    """Ball rhythm of a dribble clip: bounces (lowest ball points), bounces_per_10m (needs m_per_px for the hip
    travel, else None), ball_top_vs_hip (median height of the ball's top points above the floor in leg lengths, so
    1.0 = hip height)."""
    L, fps = leg_length(kp), _fps(t)
    by = np.asarray(ball, float)[:, 1]
    out = dict(bounces=0, bounces_per_10m=None, ball_top_vs_hip=None)
    if not math.isfinite(L) or not np.isfinite(by).any():
        return out
    bot, top = _extrema(by, fps, L, low=False), _extrema(by, fps, L, low=True)
    out["bounces"] = len(bot)
    hip = _pair(kp, T.L_HIP, T.R_HIP)
    floor = _floor(kp, fps)
    if top:
        out["ball_top_vs_hip"] = _num(float(np.nanmedian([(floor[i] - by[i]) / L for i in top])))
    hx = hip[:, 0][np.isfinite(hip[:, 0])]
    if m_per_px and len(hx) > 1 and abs(hx[-1] - hx[0]) > 0:
        out["bounces_per_10m"] = len(bot) / (abs(hx[-1] - hx[0]) * m_per_px) * 10
    return out


def compare_contacts(detected: list[dict], labelled: list[dict], tol_s: float) -> dict:
    """Match detected to hand-labelled contact onsets (nearest unused within tol_s): matched, missed, extra,
    mae_s, recall, precision (None when there is nothing to divide by)."""
    used, errs = set(), []
    for lab in sorted(labelled, key=lambda c: c["on"]):
        best = min((j for j in range(len(detected)) if j not in used), default=None,
                   key=lambda j: abs(detected[j]["on"] - lab["on"]))
        if best is not None and abs(detected[best]["on"] - lab["on"]) <= tol_s:
            used.add(best)
            errs.append(abs(detected[best]["on"] - lab["on"]))
    m = len(errs)
    return dict(matched=m, missed=len(labelled) - m, extra=len(detected) - m,
                mae_s=float(np.mean(errs)) if errs else None,
                recall=m / len(labelled) if labelled else None,
                precision=m / len(detected) if detected else None)


def gate(check: dict, fps: float) -> bool:
    """A metric may be shown when the hand-label check finds >= 80 % of contacts, >= 80 % of detections are real
    and onsets are off by <= 1.5 frames on average (our rule)."""
    return bool(check.get("recall") is not None and check["recall"] >= GATE_RECALL
                and check.get("precision") is not None and check["precision"] >= GATE_PRECISION
                and check.get("mae_s") is not None and check["mae_s"] <= GATE_MAE_FRAMES / fps + 1e-9)
