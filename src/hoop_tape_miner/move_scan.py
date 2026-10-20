"""Scan a movement session: the player's pose in every segment at its native frame rate, then 2D gait metrics.

usage: hoop-tape-miner move-scan <movement folder> [--force] [--repick] [--only S01,S03]

For each segment of movement.json, runs YOLO pose (and the ball detector for layup and dribble-sprint segments, or
any segment with "follow": "ball") on the segment's window of its *source* video at scan_fps (native, capped at 120
real frames per second), picks the player and writes to the session's run folder:
  seg/<id>.raw.npz everyone the models saw; --repick chooses the player again from it without re-running them
  seg/<id>.npz     the player: t (source s), kp, conf, box, ball, size; reused on the next run (--force to redo)
The player: when the ball was scanned and the segment has an "anchor" (else "release") time, the person holding the
ball nearest that time, followed backward and forward from there; otherwise "seed", else the largest person.
  gait/<id>.json   direction, leg length, foot contacts, per-step metrics, clip summary, layup / dribble metrics
  gait.json        all segments in one list
Game-view segments are review-only: no pose, gait/<id>.json says "metrics": null. Only side-view segments are
"measurable": 2D angles, step lengths and contacts from a front, behind or game camera are not valid, so pages show
no numbers for them (the agent review of the key frames covers them). Times in the json files are
source seconds; durations (step_time, contact_s) are real seconds (an exported slow-motion file is scaled back).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import gait as G
from . import movement as M
from . import train_scan as S
from . import training as T

BALL_KINDS = ("layup", "dribble-sprint")
ANCHOR_SEARCH_S = 0.5
CROWD_SHARE = 0.1     # more than one person in over 10 % of the frames -> identity sheet
FEAT_BINS = (8, 4, 4)  # HSV histogram bins
APPEAR_W = 1.0        # weight of the clothing-colour difference (0-1) against the move in body heights
MAX_MOVE = 1.5        # a box further than this many body heights from the last one is not the player
WHO_TILE_H = 420


def ball_anchor(raw: dict, anchor_t: float) -> tuple[int, int] | None:
    """(frame, box) of the person holding the ball nearest `anchor_t`, within ANCHOR_SEARCH_S; None when nobody is
    seen holding it (the ball detector misses most frames of a far behind-the-basket camera)."""
    t = np.asarray(raw["t"], float)
    valid = [np.isfinite(b[:, 0]) for b in raw["boxes"]]
    for i in np.argsort(np.abs(t - anchor_t), kind="stable"):
        if abs(t[i] - anchor_t) > ANCHOR_SEARCH_S:
            break
        bl = raw["balls"][i][np.isfinite(raw["balls"][i][:, 0])]
        k = T.ball_holder(raw["boxes"][i][valid[i]], raw["kps"][i][valid[i]], raw["confs"][i][valid[i]], bl)
        if k is not None:
            return int(i), k
    return None


def anchored(raw: dict, anchor_t: float, feats: list[np.ndarray] | None = None) -> list[int | None] | None:
    """Box index per frame (among that frame's valid boxes) for the person holding the ball nearest `anchor_t`,
    followed backward and forward from there (track). A trainer or defender crossing the player swaps a
    forward-only track at the rim; anchoring on the ball keeps the shooter. None without a ball anchor."""
    a = ball_anchor(raw, anchor_t)
    return None if a is None else track(valid_boxes(raw), feats, *a)


def valid_boxes(raw: dict) -> list[np.ndarray]:
    return [b[np.isfinite(b[:, 0])] for b in raw["boxes"]]


def crowded(raw: dict) -> bool:
    """More than one person in over CROWD_SHARE of the frames: the player needs an identity check."""
    n = np.array([len(b) for b in valid_boxes(raw)])
    return bool(len(n)) and float((n > 1).mean()) > CROWD_SHARE


def box_features(frame: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """(M, 128) appearance of each box: an HSV colour histogram (8 hue x 4 saturation x 4 value) of the box's central
    part, summing to 1. Clothing colour tells the player from a trainer when the two touch at the rim."""
    import cv2
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    H, W = frame.shape[:2]
    out = np.zeros((len(boxes), FEAT_BINS[0] * FEAT_BINS[1] * FEAT_BINS[2]))
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        w = x1 - x0
        xa, xb = int(max(0, x0 + 0.2 * w)), int(min(W, x1 - 0.2 * w))
        ya, yb = int(max(0, y0)), int(min(H, y1))
        if xb <= xa or yb <= ya:
            continue
        h = cv2.calcHist([hsv[ya:yb, xa:xb]], [0, 1, 2], None, list(FEAT_BINS), [0, 180, 0, 256, 0, 256]).ravel()
        out[k] = h / max(h.sum(), 1.0)
    return out


def features(seg: dict, raw: dict) -> list[np.ndarray]:
    """box_features for every frame of a scanned window (frames read again from the source)."""
    from .move_sheets import read_frames
    t = [float(x) for x in raw["t"]]
    frames = read_frames(Path(seg["source"]), t)
    boxes = valid_boxes(raw)
    return [box_features(frames[x], b) if x in frames and len(b) else np.zeros((len(b), 128))
            for x, b in zip(t, boxes)]


def track(boxes: list[np.ndarray], feats: list[np.ndarray] | None, i0: int, k0: int) -> list[int | None]:
    """Box index per frame for the person who is box k0 in frame i0, followed forward and backward: each frame takes
    the box with the lowest distance (centre moved, in body heights) + APPEAR_W x appearance difference from the
    person's colour template; nobody within MAX_MOVE body heights = not seen in that frame."""
    def run(order):
        tpl = feats[i0][k0] if feats is not None else None
        b = boxes[i0][k0]
        prev = (np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]), b[3] - b[1])
        sel = {}
        for i in order:
            bx = boxes[i]
            if not len(bx):
                continue
            c = np.c_[(bx[:, 0] + bx[:, 2]) / 2, (bx[:, 1] + bx[:, 3]) / 2]
            d = np.linalg.norm(c - prev[0], axis=1) / max(prev[1], 1.0)
            cost = d.copy()
            if tpl is not None and len(feats[i]) == len(bx):
                cost += APPEAR_W * (1 - np.sqrt(feats[i] * tpl).sum(axis=1))  # 1 - Bhattacharyya coefficient
            k = int(np.argmin(cost))
            if d[k] > MAX_MOVE:
                continue
            sel[i] = k
            prev = (c[k], bx[k, 3] - bx[k, 1])
            if tpl is not None and len(feats[i]) == len(bx) and (len(bx) == 1 or np.sort(d)[1] > 1.0):
                tpl = 0.9 * tpl + 0.1 * feats[i][k]  # learn slowly, and only when nobody else is close
        return sel
    fwd, back = run(range(i0 + 1, len(boxes))), run(range(i0 - 1, -1, -1))
    return [k0 if i == i0 else fwd.get(i, back.get(i)) for i in range(len(boxes))]


def who_times(seg: dict, raw: dict) -> list[float]:
    """Frames of the identity sheet: 1 s before, at and 0.5 s after the anchor (else release, else the middle of the
    window), snapped to scanned frames."""
    t = np.asarray(raw["t"], float)
    a, b = M.seg_seconds(seg)
    at = seg.get("anchor", seg.get("release"))
    at = M.secs(at) if at is not None else (a + b) / 2
    out = []
    for x in (at - 1.0, at, at + 0.5):
        x = float(t[int(np.argmin(np.abs(t - x)))])
        if x not in out:
            out.append(x)
    return out


def who_sheet(seg: dict, raw: dict, out: Path) -> dict:
    """who_<id>.jpg: the who_times frames with every detected person boxed and numbered (the number `who` uses);
    returns the who.json entry {"times": [...], "t": None, "box": None} for the agent to fill."""
    import cv2

    from . import train_sheets as TS
    from .move_sheets import read_frames
    times = who_times(seg, raw)
    frames = read_frames(Path(seg["source"]), times)
    t = np.asarray(raw["t"], float)
    tiles = []
    for x in times:
        if x not in frames:
            continue
        f = frames[x].copy()
        bx = valid_boxes(raw)[int(np.argmin(np.abs(t - x)))]
        th = max(2, f.shape[0] // 300)
        for k, (x0, y0, x1, y1) in enumerate(bx):
            cv2.rectangle(f, (int(x0), int(y0)), (int(x1), int(y1)), (0, 255, 255), th)
            cv2.putText(f, str(k), (int(x0) + 4, int(y0) + 14 * th), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * th,
                        (0, 0, 255), th + 1)
        if len(bx):
            x0, y0 = bx[:, 0].min(), bx[:, 1].min()
            x1, y1 = bx[:, 2].max(), bx[:, 3].max()
            pw, ph = 0.25 * (x1 - x0) + 40, 0.15 * (y1 - y0) + 20
            f = TS.crop(f, x0 - pw, y0 - ph, x1 + pw, y1 + ph)
        tiles.append(TS.label(TS.resize_h(f, WHO_TILE_H), f"{seg['id']} {_mmss(x)}", 0.7))
    if tiles:
        cv2.imwrite(str(out), TS.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return {"times": [_mmss(x) for x in times], "t": None, "box": None}


def _mmss(x: float) -> str:
    return f"{int(x // 60):02d}:{x % 60:04.1f}"


def pick_segment(seg: dict, raw: dict, feats: list[np.ndarray] | None = None) -> dict:
    """The player's track in one segment from scan() output, by the first identity source the segment has:
    "who" {"t", "box"} (an agent picked the numbered box on the identity sheet), the person holding the ball at
    "anchor" (else "release"), else "seed" / the largest person (train_scan.pick). The first two are followed both
    ways from that frame, with clothing colour when `feats` is given."""
    t = np.asarray(raw["t"], float)
    boxes = valid_boxes(raw)
    who = seg.get("who") or {}
    if who.get("box") is not None and who.get("t") is not None and len(t):
        tw = M.secs(who["t"])
        sheet = min(who_times(seg, raw), key=lambda x: abs(x - tw))
        if abs(sheet - tw) <= 0.06:  # captions are rounded to 0.1 s: use the exact sheet frame the numbers belong to
            tw = sheet
        i0 = int(np.argmin(np.abs(t - tw)))
        if int(who["box"]) < len(boxes[i0]):
            return S.assemble(raw, track(boxes, feats, i0, int(who["box"])))
    at = seg.get("anchor", seg.get("release"))
    if at is not None and "balls" in raw:
        sel = anchored(raw, M.secs(at), feats)
        if sel is not None:
            return S.assemble(raw, sel)
    return S.pick(raw, tuple(seg["seed"]) if seg.get("seed") else None, "player")


def _r(v, nd=3):
    """Round floats for json; NaN / inf become None (unknown)."""
    if isinstance(v, (float, np.floating)):
        return round(float(v), nd) if np.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, dict):
        return {k: _r(x, nd) for k, x in v.items()}
    if isinstance(v, list):
        return [_r(x, nd) for x in v]
    return v


def release_time(t: np.ndarray, kp: np.ndarray, conf: np.ndarray) -> float | None:
    """Ball release of a layup when the segment does not give one: the highest wrist lift in the window, if the
    hands got at least LIFT_MIN torso lengths above the shoulders."""
    b = T.body_series(t, T.masked(kp, conf))
    lift = b["lift"]
    if not np.isfinite(lift).any() or np.nanmax(lift) < T.LIFT_MIN:
        return None
    return float(t[int(np.nanargmax(lift))])


def metrics(seg: dict, d: dict) -> dict:
    """gait/<id>.json content from the picked pose of one segment."""
    a, _ = M.seg_seconds(seg)
    k = M.slowmo(seg)
    t_src = np.asarray(d["t"], float)
    t = a + (t_src - a) / k  # real-time clock, equal to source time unless the file is slowed down
    back = lambda x: None if x is None else a + (x - a) * k
    kp, conf = d["kp"], d["conf"]
    contacts = G.foot_contacts(t, kp, conf)
    steps = G.step_metrics(t, kp, conf, contacts)
    real_fps = float(1 / np.median(np.diff(t))) if len(t) > 1 else 0.0
    out = dict(id=seg["id"], kind=seg["kind"], view=seg["view"], fps=seg.get("fps"), scan_fps=seg.get("scan_fps"),
               real_fps=round(real_fps, 2), metrics_version=G.METRICS_VERSION, measurable=seg["view"] == "side",
               direction=G.direction(t, kp),
               leg_px=G.leg_length(T.masked(kp, conf)),
               visible_share=float(np.isfinite(T.masked(kp, conf)[:, T.L_HIP, 0]).mean()) if len(t) else 0.0,
               contacts=[dict(c, on=back(c["on"]), off=back(c["off"])) for c in contacts],
               steps=[dict(s, t=back(s["t"])) for s in steps], clip=G.clip_metrics(steps, real_fps))
    if seg["kind"] == "layup":
        rel = M.secs(seg["release"]) if seg.get("release") is not None else release_time(t_src, kp, conf)
        out["release"] = rel
        if rel is not None:
            lay = G.layup_metrics(t, kp, conf, contacts, a + (rel - a) / k)
            lay["takeoff_t"] = back(lay["takeoff_t"])
            out["layup"] = lay
    if seg["kind"] == "dribble-sprint":
        out["dribble"] = G.dribble_metrics(t, T.masked(kp, conf), d["ball"])
    return _r(out)


def scan_segments(folder: Path, force: bool = False, only: list[str] | None = None, scanner=None,
                  repick: bool = False) -> list[str]:
    """Pose + metrics for the segments of a movement session; returns the ids that were scanned (not reused).
    repick: choose the player again from seg/<id>.raw.npz (and scan only where that is missing)."""
    scanner = scanner or S.scan
    m = M.load(folder)
    run = M.path(folder, m, "run", "run")
    (run / "seg").mkdir(parents=True, exist_ok=True)
    (run / "gait").mkdir(parents=True, exist_ok=True)
    who_path = run / "move_review" / "who.json"
    who_all = json.loads(who_path.read_text(encoding="utf8")) if who_path.exists() else {}
    if merge_who(m, who_all):
        M.save(folder, m)
    scanned, allg = [], []
    for seg in m.get("segments", []):
        sid = seg["id"]
        gpath = run / "gait" / f"{sid}.json"
        if only and sid not in only:
            if gpath.exists():
                allg.append(json.loads(gpath.read_text(encoding="utf8")))
            continue
        if seg["view"] == "game":
            g = dict(id=sid, kind=seg["kind"], view="game", metrics=None, measurable=False)
        else:
            npz, raw_npz = run / "seg" / f"{sid}.npz", run / "seg" / f"{sid}.raw.npz"
            raw = None
            if raw_npz.exists() and not force:
                z = np.load(raw_npz)
                raw = {k: z[k] for k in z.files}
            if npz.exists() and not force and not repick:
                z = np.load(npz)
                d = {k: z[k] for k in z.files}
            else:
                if raw is None:
                    a, b = M.seg_seconds(seg)
                    print(f"[move-scan] {sid} {seg['kind']}/{seg['view']} {seg['from']}-{seg['to']} at "
                          f"{seg.get('scan_fps')} fps", flush=True)
                    ball = seg["kind"] in BALL_KINDS or seg.get("follow") == "ball"
                    raw = scanner(Path(seg["source"]), float(seg.get("scan_fps") or 30), ball, a, b)
                    np.savez_compressed(raw_npz, **raw)
                    scanned.append(sid)
                feats = None
                if crowded(raw) and Path(seg["source"]).is_file():
                    feats = cached_features(seg, raw, run / "seg" / f"{sid}.feat.npz", force)
                d = pick_segment(seg, raw, feats)
                np.savez_compressed(npz, **d)
            g = metrics(seg, d)
            g["crowded"] = raw is not None and crowded(raw)
            if g["crowded"] and (seg.get("who") or {}).get("box") is None and Path(seg["source"]).is_file():
                img = run / "move_review" / f"who_{sid}.jpg"
                img.parent.mkdir(parents=True, exist_ok=True)
                entry = who_sheet(seg, raw, img) if force or not img.exists() else \
                    {"times": [_mmss(x) for x in who_times(seg, raw)], "t": None, "box": None}
                who_all[sid] = {**entry, **{k: v for k, v in who_all.get(sid, {}).items() if v is not None}}
        gpath.write_text(json.dumps(g, indent=1) + "\n", encoding="utf8")
        allg.append(g)
    (run / "gait.json").write_text(json.dumps(allg, indent=1) + "\n", encoding="utf8")
    if who_all:
        who_path.write_text(json.dumps(who_all, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
    n_steps = sum(len(g.get("steps") or []) for g in allg)
    print(f"[move-scan] {len(allg)} segments ({len(scanned)} scanned, the rest reused), {n_steps} steps found")
    open_who = [s["id"] for s in m.get("segments", []) if s["id"] in who_all and (s.get("who") or {}).get("box") is None]
    if open_who:
        print(f"[move-scan] identity check needed ({len(open_who)} segments with more than one person): "
              f"{who_path} and who_<id>.jpg")
    return scanned


def merge_who(m: dict, who_all: dict) -> bool:
    """Copy the agent's picks from who.json ({"<id>": {"times": [...], "t": "mm:ss.s", "box": 1}}) into the
    segments' "who"; t defaults to the middle sheet frame. Returns True when movement.json changed."""
    changed = False
    for seg in m.get("segments", []):
        e = who_all.get(seg["id"]) or {}
        if e.get("box") is None:
            continue
        times = e.get("times") or []
        t = e.get("t") or (times[len(times) // 2] if times else None)
        if t is None:
            continue
        new = {"t": t, "box": int(e["box"])}
        if seg.get("who") != new:
            seg["who"], changed = new, True
    return changed


def cached_features(seg: dict, raw: dict, path: Path, force: bool = False) -> list[np.ndarray]:
    """features() per frame, cached in seg/<id>.feat.npz (aligned with raw boxes; invalid boxes are zero rows)."""
    valid = [np.isfinite(b[:, 0]) for b in raw["boxes"]]
    if path.exists() and not force:
        full = np.load(path)["feat"]
        if len(full) == len(valid):
            return [f[v] for f, v in zip(full, valid)]
    feats = features(seg, raw)
    full = np.zeros(raw["boxes"].shape[:2] + (feats[0].shape[1] if feats else 128,))
    for i, (f, v) in enumerate(zip(feats, valid)):
        full[i][v] = f
    np.savez_compressed(path, feat=full)
    return feats


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner move-scan", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="movement session folder (with movement.json)")
    ap.add_argument("--force", action="store_true", help="re-run pose even where seg/<id>.npz exists")
    ap.add_argument("--repick", action="store_true", help="choose the player again from seg/<id>.raw.npz")
    ap.add_argument("--only", help="comma-separated segment ids")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    if not M.is_movement(folder):
        sys.exit(f"no movement.json in {folder}")
    scan_segments(folder, a.force, a.only.split(",") if a.only else None, repick=a.repick)


if __name__ == "__main__":
    main()
