"""Scan a training session video: body pose of the main player, shot / finish candidates, dribble segments.

usage: hoop-tape-miner train-scan <session folder> [--fps 15] [--seed 0.5,0.6] [--no-ball] [--force]

Runs ultralytics YOLO pose (yolo11s-pose) and, unless --no-ball, the COCO detector (yolo11s, class "sports ball")
on every frame at --fps, follows the main player (largest person at the start, or the one nearest --seed x,y frame
fractions) and writes to the session's run folder:
  pose.npz       t, kp (N,17,2 px), conf (N,17), box (N,4 xyxy), ball (N,2 centre px), size (w,h)
  reps.json      shot / finish candidates with form metrics (training.find_reps); the film review confirms them
  dribble.json   dribble segments from wrist rhythm (training.find_dribbles), ball_seen when the ball was detected
  activity.json  per 5 s window: player visible share and hip speed; totals
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


def frames(video: Path, fps: float):
    """Yield (t, frame) at about `fps` frames per second, reading the video once."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"cannot open {video}")
    src = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(src / fps))
    i = 0
    while cap.grab():
        if i % step == 0:
            ok, f = cap.retrieve()
            if ok:
                yield i / src, f
        i += 1
    cap.release()


def scan(video: Path, fps: float = 15.0, ball: bool = True, seed: tuple[float, float] | None = None) -> dict:
    import torch
    dev = 0 if torch.cuda.is_available() else "cpu"
    pose_m = model(POSE_MODEL)
    ball_m = model(BALL_MODEL) if ball else None
    ts, boxes, kps, confs, balls, size = [], [], [], [], [], None

    def run(batch):
        imgs = [f for _, f in batch]
        res = pose_m(imgs, verbose=False, device=dev, half=dev != "cpu", conf=0.25)
        bres = ball_m(imgs, verbose=False, device=dev, half=dev != "cpu", conf=0.15, classes=[BALL_CLASS]) if ball_m else [None] * len(imgs)
        for (t, _), r, b in zip(batch, res, bres):
            ts.append(t)
            if r.keypoints is not None and len(r.boxes):
                boxes.append(r.boxes.xyxy.cpu().numpy())
                kps.append(r.keypoints.xy.cpu().numpy())
                confs.append(r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else np.ones(r.keypoints.xy.shape[:2]))
            else:
                boxes.append(np.zeros((0, 4)))
                kps.append(np.zeros((0, 17, 2)))
                confs.append(np.zeros((0, 17)))
            if b is not None and len(b.boxes):
                bb = b.boxes.xyxy.cpu().numpy()
                balls.append(np.c_[(bb[:, 0] + bb[:, 2]) / 2, (bb[:, 1] + bb[:, 3]) / 2])
            else:
                balls.append(np.zeros((0, 2)))

    batch = []
    for n, (t, f) in enumerate(frames(video, fps)):
        size = size or (f.shape[1], f.shape[0])
        batch.append((t, f))
        if len(batch) == BATCH:
            run(batch)
            batch = []
        if n and n % (int(fps) * 60) == 0:
            print(f"[train-scan] {t / 60:.0f} min", flush=True)
    if batch:
        run(batch)
    pick = T.pick_main(boxes, seed, size)
    N = len(ts)
    kp, conf, box, ballc = np.full((N, 17, 2), np.nan), np.zeros((N, 17)), np.full((N, 4), np.nan), np.full((N, 2), np.nan)
    for i, k in enumerate(pick):
        if k is None:
            continue
        kp[i], conf[i], box[i] = kps[i][k], confs[i][k], boxes[i][k]
        if len(balls[i]):  # the ball nearest the player's hands
            hands = kp[i, [T.L_WR, T.R_WR]]
            hands = hands[np.isfinite(hands).all(1)]
            ref = hands.mean(0) if len(hands) else np.array([(box[i, 0] + box[i, 2]) / 2, (box[i, 1] + box[i, 3]) / 2])
            ballc[i] = balls[i][int(np.argmin(np.linalg.norm(balls[i] - ref, axis=1)))]
    return dict(t=np.array(ts), kp=kp, conf=conf, box=box, ball=ballc, size=np.array(size or (0, 0)))


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
    run.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(run / "pose.npz", **d)
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
    ap.add_argument("--seed", help="x,y frame fractions of the player at the start, when others are in the frame")
    ap.add_argument("--no-ball", action="store_true", help="skip ball detection (faster; dribbles from pose only)")
    ap.add_argument("--force", action="store_true", help="re-run even if pose.npz exists")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    s = T.load_session(folder)
    run = T.session_path(folder, s, "run", "run")
    video = T.session_path(folder, s, "video", "session.mp4")
    if not video.is_file():
        sys.exit(f"session video not found: {video}")
    if (run / "pose.npz").exists() and not a.force:
        z = np.load(run / "pose.npz")
        d = {k: z[k] for k in z.files}
        print("[train-scan] reusing pose.npz (--force to re-run the models)")
    else:
        seed = tuple(map(float, a.seed.split(","))) if a.seed else None
        d = scan(video, a.fps, not a.no_ball, seed)
    write(run, d)


if __name__ == "__main__":
    main()
