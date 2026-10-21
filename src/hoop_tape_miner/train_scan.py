"""Scan a training session video: body pose of the main player, shot / finish candidates, dribble segments.

usage: hoop-tape-miner train-scan <session folder> [--fps 15] [--seed 0.5,0.6] [--no-ball] [--follow player|ball] [--force] [--repick]

Runs ultralytics YOLO pose (yolo11s-pose) and, unless --no-ball, the COCO detector (yolo11s, class "sports ball")
on every frame at --fps, follows the main player (largest person at the start, or the one nearest --seed x,y frame
fractions; with --follow ball, or session.json "follow": "ball", whoever holds the ball, for sessions with a
trainer or partner in frame) and writes to the session's run folder:
  pose_all.npz   every person and ball per frame, so --repick needs no models
  pose.npz       t, kp (N,17,2 px), conf (N,17), box (N,4 xyxy), ball (N,2 centre px), size (w,h)
  reps.json      shot / finish candidates with form metrics (training.find_reps); the film review confirms them
  dribble.json   dribble segments from wrist rhythm (training.find_dribbles), ball_seen when the ball was detected
  activity.json  per 5 s window: player visible share and hip speed; totals
Both npz files store the inputs they were made from: pose_all.npz is scanned again when the video's content,
--fps or the ball pass change, pose.npz is picked again from pose_all.npz when the seed or follow change.
Weights download once to ~/.cache/hoop-tape-miner/. GPU when available, else CPU (slower, still fine for a short
session).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import training as T

WEIGHTS = Path.home() / ".cache" / "hoop-tape-miner"
POSE_MODEL, BALL_MODEL, BALL_CLASS = "yolo11s-pose.pt", "yolo11s.pt", 32
BATCH = 16


def model(name: str):
    from ultralytics import YOLO
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    return YOLO(str(WEIGHTS / name))


def frames(video: Path, fps: float, t0: float = 0.0, t1: float | None = None):
    """Yield (t, frame) at about `fps` frames per second, reading the video once; with t0 / t1 only that window
    (t stays in source seconds)."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"cannot open {video}")
    src = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if t0 <= 0 and t1 is None:
        step = max(1, round(src / fps))
        i = 0
        while cap.grab():
            if i % step == 0:
                ok, f = cap.retrieve()
                if ok:
                    yield i / src, f
            i += 1
        cap.release()
        return
    if t0 > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
    nxt = t0
    while cap.grab():
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if t1 is not None and t > t1 + 1e-6:
            break
        if t >= nxt - 0.5 / src:
            ok, f = cap.retrieve()
            if ok:
                yield t, f
            nxt = max(nxt + 1 / fps, t + 0.5 / src)
    cap.release()


MAX_PEOPLE, MAX_BALLS = 6, 4  # per frame, kept in pose_all.npz (largest people, most confident balls)
FP_BYTES = 1 << 20  # fingerprint: the first and last MiB of a video, plus its size


# ---- cache keys ----------------------------------------------------------------------------------------------

def fingerprint(path: Path) -> str:
    """Content key of a video that survives a copy or a move: size + sha1 of its first and last MiB; "" when the
    file is missing (the key then cannot tell, and a cache is reused)."""
    import hashlib
    p = Path(path)
    if not p.is_file():
        return ""
    n = p.stat().st_size
    h = hashlib.sha1(str(n).encode())
    with open(p, "rb") as f:
        h.update(f.read(FP_BYTES))
        if n > 2 * FP_BYTES:
            f.seek(-FP_BYTES, 2)
            h.update(f.read(FP_BYTES))
    return f"{n}:{h.hexdigest()[:16]}"


def save_npz(path: Path, d: dict, key: dict | None = None) -> None:
    """np.savez_compressed with the inputs the arrays were made from stored as "key" (a json string)."""
    extra = {} if key is None else {"key": np.array(json.dumps(key, sort_keys=True))}
    np.savez_compressed(path, **{k: v for k, v in d.items() if k != "key"}, **extra)


def load_npz(path: Path) -> tuple[dict, dict | None]:
    """(arrays, key) of a save_npz file; key None for files written before keys were stored."""
    z = np.load(path)
    key = json.loads(str(z["key"])) if "key" in z.files else None
    return {k: z[k] for k in z.files if k != "key"}, key


def same_key(stored: dict | None, key: dict) -> bool:
    return stored is not None and json.dumps(stored, sort_keys=True) == json.dumps(key, sort_keys=True)


def scan(video: Path, fps: float = 15.0, ball: bool = True, t0: float = 0.0, t1: float | None = None) -> dict:
    """Every person (box, keypoints) and ball in each analysed frame (only t0..t1 when given), padded with NaN:
    t (N,), boxes (N,M,4), kps (N,M,17,2), confs (N,M,17), balls (N,B,2), size (w,h)."""
    import torch
    dev = 0 if torch.cuda.is_available() else "cpu"
    pose_m = model(POSE_MODEL)
    ball_m = model(BALL_MODEL) if ball else None
    ts, size = [], None
    rows: dict[str, list] = {"boxes": [], "kps": [], "confs": [], "balls": []}

    def run(batch):
        imgs = [f for _, f in batch]
        res = pose_m(imgs, verbose=False, device=dev, half=dev != "cpu", conf=0.25)
        bres = ball_m(imgs, verbose=False, device=dev, half=dev != "cpu", conf=0.15, classes=[BALL_CLASS]) if ball_m else [None] * len(imgs)
        for (t, _), r, b in zip(batch, res, bres):
            ts.append(t)
            bx, kp = np.full((MAX_PEOPLE, 4), np.nan, np.float32), np.full((MAX_PEOPLE, 17, 2), np.nan, np.float32)
            cf = np.zeros((MAX_PEOPLE, 17), np.float32)
            if r.keypoints is not None and len(r.boxes):
                B = r.boxes.xyxy.cpu().numpy()
                K = r.keypoints.xy.cpu().numpy()
                C = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else np.ones(K.shape[:2])
                order = np.argsort(-(B[:, 2] - B[:, 0]) * (B[:, 3] - B[:, 1]))[:MAX_PEOPLE]
                for j, i in enumerate(order):
                    bx[j], kp[j], cf[j] = B[i], K[i], C[i]
            bl = np.full((MAX_BALLS, 2), np.nan, np.float32)
            if b is not None and len(b.boxes):
                bb = b.boxes.xyxy.cpu().numpy()[np.argsort(-b.boxes.conf.cpu().numpy())][:MAX_BALLS]
                bl[:len(bb)] = np.c_[(bb[:, 0] + bb[:, 2]) / 2, (bb[:, 1] + bb[:, 3]) / 2]
            for k, v in zip(("boxes", "kps", "confs", "balls"), (bx, kp, cf, bl)):
                rows[k].append(v)

    batch = []
    for n, (t, f) in enumerate(frames(video, fps, t0, t1)):
        size = size or (f.shape[1], f.shape[0])
        batch.append((t, f))
        if len(batch) == BATCH:
            run(batch)
            batch = []
        if n and n % max(1, int(fps) * 60) == 0:
            print(f"[train-scan] {t / 60:.0f} min", flush=True)
    if batch:
        run(batch)
    out = {k: np.array(v) for k, v in rows.items()}
    return dict(t=np.array(ts), size=np.array(size or (0, 0)), **out)


def pick(raw: dict, seed: tuple[float, float] | None = None, follow: str = "player") -> dict:
    """The main player's track from scan() output (pose.npz content): t, kp, conf, box, ball (nearest the
    player's hands), size. follow "player" = the seed / largest person by position; "ball" = whoever holds the
    ball (a trainer or partner in frame, see training.pick_ball_carrier)."""
    ts, size = raw["t"], tuple(int(v) for v in raw["size"])
    valid = [np.isfinite(b[:, 0]) for b in raw["boxes"]]
    boxes = [b[m] for b, m in zip(raw["boxes"], valid)]
    if follow == "ball":
        balls = [b[np.isfinite(b[:, 0])] for b in raw["balls"]]
        sel = T.pick_ball_carrier(boxes, [k[m] for k, m in zip(raw["kps"], valid)],
                                  [c[m] for c, m in zip(raw["confs"], valid)], balls, seed, size)
    else:
        sel = T.pick_main(boxes, seed, size)
    return assemble(raw, sel)


def assemble(raw: dict, sel: list[int | None]) -> dict:
    """pick() output from one chosen box index per frame (index among that frame's valid boxes, or None)."""
    ts, size = raw["t"], tuple(int(v) for v in raw["size"])
    valid = [np.isfinite(b[:, 0]) for b in raw["boxes"]]
    N = len(ts)
    kp, conf, box, ballc = np.full((N, 17, 2), np.nan), np.zeros((N, 17)), np.full((N, 4), np.nan), np.full((N, 2), np.nan)
    for i, k in enumerate(sel):
        if k is None:
            continue
        j = int(np.flatnonzero(valid[i])[k])
        kp[i], conf[i], box[i] = raw["kps"][i][j], raw["confs"][i][j], raw["boxes"][i][j]
        balls = raw["balls"][i][np.isfinite(raw["balls"][i][:, 0])]
        if len(balls):  # the ball nearest the player's hands
            hands = kp[i, [T.L_WR, T.R_WR]]
            hands = hands[np.isfinite(hands).all(1)]
            ref = hands.mean(0) if len(hands) else np.array([(box[i, 0] + box[i, 2]) / 2, (box[i, 1] + box[i, 3]) / 2])
            ballc[i] = balls[int(np.argmin(np.linalg.norm(balls - ref, axis=1)))]
    return dict(t=np.array(ts), kp=kp, conf=conf, box=box, ball=ballc, size=np.array(size))


def activity(d: dict, window: float = 5.0) -> dict:
    """Visible share and median hip speed (torso lengths / s) per window; active = visible and moving or lifting."""
    t = d["t"]
    kp = T.masked(d["kp"], d["conf"])
    b = T.body_series(t, kp)
    with np.errstate(all="ignore"):
        speed = np.r_[np.nan, np.linalg.norm(np.diff(b["hip"], axis=0), axis=1) / np.diff(t)] / b["torso"]
    out, active = [], 0.0
    for t0 in np.arange(0, (t[-1] if len(t) else 0) + 1e-6, window):
        m = (t >= t0) & (t < t0 + window)
        if not m.any():
            continue
        vis = float(np.isfinite(b["hip"][m, 0]).mean())
        sp = float(np.nanmedian(speed[m])) if np.isfinite(speed[m]).any() else None
        lift = float(np.nanmax(b["lift"][m])) if np.isfinite(b["lift"][m]).any() else None
        on = vis > 0.5 and ((sp or 0) > 0.25 or (lift or -9) > T.LIFT_MIN)
        active += window if on else 0
        out.append(dict(t=round(float(t0), 1), visible=round(vis, 2), speed=T._r(sp), active=on))
    return dict(window_s=window, duration_s=round(float(t[-1]) if len(t) else 0.0, 1),
                visible_s=round(sum(w["visible"] for w in out) * window, 1), active_s=round(active, 1), windows=out)


def write(run: Path, d: dict):
    """reps.json, dribble.json and activity.json from the main player's pose (pose.npz is saved by pose_for)."""
    run.mkdir(parents=True, exist_ok=True)
    reps = T.find_reps(d["t"], d["kp"], d["conf"])
    drib = T.find_dribbles(d["t"], d["kp"], d["conf"], d["ball"] if np.isfinite(d["ball"]).any() else None)
    act = activity(d)
    (run / "reps.json").write_text(json.dumps(reps, indent=1) + "\n", encoding="utf8")
    (run / "dribble.json").write_text(json.dumps(drib, indent=1) + "\n", encoding="utf8")
    (run / "activity.json").write_text(json.dumps(act, indent=1) + "\n", encoding="utf8")
    seen = float(np.isfinite(d["kp"][:, T.L_SH, 0]).mean()) if len(d["t"]) else 0.0
    print(f"[train-scan] {len(d['t'])} frames, player visible {seen:.0%}; {len(reps)} rep candidates, "
          f"{len(drib)} dribble segments, active {act['active_s'] / 60:.1f} of {act['duration_s'] / 60:.1f} min")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner train-scan", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="session folder (with session.json)")
    ap.add_argument("--fps", type=float, default=15.0, help="frames per second to analyse (default 15)")
    ap.add_argument("--seed", help="x,y frame fractions of the player at the start, when others are in the frame "
                    "(default: session.json \"seed\")")
    ap.add_argument("--no-ball", action="store_true", help="skip ball detection (faster; dribbles from pose only)")
    ap.add_argument("--force", action="store_true", help="re-run even if pose.npz exists")
    ap.add_argument("--follow", choices=("player", "ball"),
                    help="player = the seed / largest person (default); ball = whoever holds the ball, when a trainer "
                    "or partner is in frame (default: session.json \"follow\")")
    ap.add_argument("--repick", action="store_true",
                    help="choose the player again from pose_all.npz (e.g. with a new --seed) without re-running the models")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    s = T.load_session(folder)
    run = T.session_path(folder, s, "run", "run")
    video = T.session_path(folder, s, "video", "session.mp4")
    if not video.is_file():
        sys.exit(f"session video not found: {video}")
    seed = tuple(map(float, a.seed.split(","))) if a.seed else (tuple(s["seed"]) if s.get("seed") else None)
    follow = a.follow or s.get("follow") or "player"
    if a.repick and not (run / "pose_all.npz").exists():
        sys.exit(f"--repick needs {run / 'pose_all.npz'} (scans before this option kept only the main player)")
    write(run, pose_for(run, video, a.fps, not a.no_ball, seed, follow, a.force, a.repick))


def pose_for(run: Path, video: Path, fps: float, ball: bool, seed, follow: str, force: bool = False,
             repick: bool = False, scanner=None) -> dict:
    """The main player's pose (pose.npz content), reusing the caches while their inputs are unchanged:
    pose_all.npz is scanned again when the video's content, --fps or the ball pass changed (files from before keys
    are reused); pose.npz is picked again from pose_all.npz when the seed or follow changed (or with --repick)."""
    scanner = scanner or scan
    rk = dict(video=fingerprint(video), fps=float(fps), ball=bool(ball))
    pk = dict(raw=rk, seed=list(seed) if seed else None, follow=follow)
    all_p, pose_p = run / "pose_all.npz", run / "pose.npz"
    raw = None
    if all_p.exists() and not force:
        raw, k = load_npz(all_p)
        if k is not None and not same_key(k, rk):
            print("[train-scan] the video, --fps or the ball pass changed: scanning again")
            raw = None
    if pose_p.exists() and not force and not repick:
        d, k = load_npz(pose_p)
        if same_key(k, pk) or (raw is None and not all_p.exists() and k is None):
            print("[train-scan] reusing pose.npz (--force to re-run the models)")
            return d
    if raw is None:
        raw = scanner(video, fps, ball)
        run.mkdir(parents=True, exist_ok=True)
        save_npz(all_p, raw, rk)
    else:
        print("[train-scan] picked the player from pose_all.npz (seed / follow changed, or --repick)")
    d = pick(raw, seed, follow)
    save_npz(pose_p, d, pk)
    return d


if __name__ == "__main__":
    main()
