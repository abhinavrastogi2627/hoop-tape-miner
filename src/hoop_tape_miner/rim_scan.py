"""Rim-zone scan: ball-sized movers in the air around each rim, from the video and the per-frame camera.

    hoop-tape-miner rim-scan --run RUN (--game GAME.json | --video V) [--out RUN/rim_scan.pkl] [--step 2]

extract's ball detector rarely fires on the ball in flight near the rim (small, blurred, against the backboard),
so shot arcs cannot come from detections.pkl alone. This stage reads the video (every `step`-th frame, ~30 fps)
and, per frame and rim, rectifies a camera-facing patch of the air around and above the hoop (2.4 m wide,
2.6-4.6 m high, 3 cm cells) with the camera pose recovered from the nearest sampled homography (ball.py). Each
patch is registered against the last second of patches (phase correlation, which absorbs homography jitter),
differenced against their median and opened with a small disk, so thin edges vanish and a moving ball stays a
blob. Ball-sized round blobs are written to rim_scan.pkl (frame, t, side, u, z, area: u lateral metres from the
hoop centre, z height in metres); shots.py links them into arcs. CPU only, roughly real time / 10.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .ball import BALL_D, SIDES, cameras, facing_grid

# patch geometry (m) and foreground / blob thresholds
SCAN = dict(cell=0.03, lat=1.2, z0=2.6, z1=4.6, thr=25, buffer_s=1.0, skip_s=0.1, every=3, min_bg=4,
            max_shift=6.0, area=(0.4, 2.6), max_side=2.2, fill=0.45, max_fg=0.2)


def ball_blobs(fg: np.ndarray, cell: float, area=(0.4, 2.6), max_side=2.2, fill=0.45) -> list[tuple]:
    """Ball-sized round blobs in a binary mask of a patch with `cell` metres per pixel: (col, row, area).

    area: accepted pixel area as a multiple of the ball's disc; max_side: largest bounding-box side in ball
    diameters; fill: smallest area / inscribed-ellipse area of the box (drops lines and L-shapes).
    """
    a_ball = np.pi * (BALL_D / 2 / cell) ** 2
    side_max = max_side * BALL_D / cell
    n, _, st, cen = cv2.connectedComponentsWithStats(fg.astype(np.uint8), connectivity=8)
    out = []
    for k in range(1, n):
        x, y, w, h, a = st[k]
        if not (area[0] * a_ball <= a <= area[1] * a_ball) or max(w, h) > side_max or a < fill * w * h * np.pi / 4:
            continue
        out.append((float(cen[k][0]), float(cen[k][1]), int(a)))
    return out


class RimScanner:
    """Stateful per-rim foreground detector over a stream of frames (see module doc). feed() returns blobs."""

    def __init__(self, fps: float, **kw):
        self.p = {**SCAN, **kw}
        c = self.p["cell"]
        self.us = np.arange(-self.p["lat"], self.p["lat"] + 1e-9, c)
        self.zs = np.arange(self.p["z1"], self.p["z0"] - 1e-9, -c)
        self.fps = fps
        self.buf = {s: deque(maxlen=max(2, int(round(self.p["buffer_s"] * fps)))) for s in SIDES}
        self.skip = max(1, int(round(self.p["skip_s"] * fps)))
        self.ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def reset(self, side=None):
        for s in ([side] if side else SIDES):
            self.buf[s].clear()

    def feed(self, img: np.ndarray, P: np.ndarray | None, side: str) -> list[tuple[float, float, int]]:
        """Blobs (u m, z m, area cells) for one frame and rim. No camera (P None) or a patch leaving the image
        resets that rim's background."""
        if P is None:
            self.reset(side)
            return []
        g = facing_grid(P, side, self.us, self.zs).astype(np.float32)
        h, w = img.shape[:2]
        if not ((g[..., 0] >= 0).all() and (g[..., 0] < w - 1).all() and (g[..., 1] >= 0).all()
                and (g[..., 1] < h - 1).all()):
            self.reset(side)
            return []
        gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        patch = cv2.remap(gray, g[..., 0], g[..., 1], cv2.INTER_LINEAR).astype(np.float32)
        buf = self.buf[side]
        prev = list(buf)[:-self.skip:self.p["every"]] if len(buf) > self.skip else []
        reg = []
        for q in prev:
            (dx, dy), _ = cv2.phaseCorrelate(patch, q)
            if np.hypot(dx, dy) > self.p["max_shift"]:
                continue
            M = np.float32([[1, 0, -dx], [0, 1, -dy]])
            reg.append(cv2.warpAffine(q, M, patch.shape[::-1], borderMode=cv2.BORDER_REPLICATE))
        blobs = []
        if len(reg) >= self.p["min_bg"]:
            bg = np.median(np.stack(reg), 0)
            fg = cv2.morphologyEx((np.abs(patch - bg) > self.p["thr"]).astype(np.uint8), cv2.MORPH_OPEN, self.ker)
            if fg.mean() <= self.p["max_fg"]:  # a whole-patch change is a cut or a lost camera, not a ball
                c = self.p["cell"]
                for col, row, a in ball_blobs(fg, c, self.p["area"], self.p["max_side"], self.p["fill"]):
                    blobs.append((float(self.us[0] + col * c), float(self.zs[0] - row * c), a))
        buf.append(patch)
        return blobs


def scan_rims(cap, cam: dict, size=(1280, 720), step: int = 2, t_range=None, log_every: float = 300.0,
              **kw) -> pd.DataFrame:
    """Run RimScanner over the video (every `step`-th frame) with the nearest sampled camera.

    Frames farther than half a sampling interval from a calibrated frame are skipped. Returns rows
    frame, t, side, u, z, area.
    """
    vfps = cap.get(cv2.CAP_PROP_FPS) or 0
    frames = np.asarray(cam["frame"]).astype(int)
    ts = np.asarray(cam["t"], float)
    if vfps <= 0:
        vfps = float(np.median(np.diff(frames) / np.diff(ts))) if len(frames) > 1 else 30.0
    Ps = cameras(cam, size)
    half = (np.median(np.diff(frames)) if len(frames) > 1 else 1) / 2
    sc = RimScanner(vfps / step, **kw)
    f0 = 0 if t_range is None else max(0, int(t_range[0] * vfps))
    f1 = int(frames.max()) if t_range is None else min(int(frames.max()), int(t_range[1] * vfps))
    if f0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    rows = []
    nxt_log = 0.0
    for fi in range(f0, f1 + 1):
        if (fi - f0) % step:
            if not cap.grab():
                break
            continue
        ok, img = cap.read()
        if not ok:
            break
        j = int(np.searchsorted(frames, fi))
        j = min(range(max(0, j - 1), min(len(frames), j + 1)), key=lambda k: abs(frames[k] - fi))
        P = Ps.get(int(frames[j])) if abs(frames[j] - fi) <= half else None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        t = fi / vfps
        for s in SIDES:
            for u, z, a in sc.feed(gray, P, s):
                rows.append((fi, round(t, 3), s, round(u, 3), round(z, 3), a))
        if log_every and t >= nxt_log:
            print(f"rim-scan {t:7.1f} s, {len(rows)} blobs", flush=True)
            nxt_log += log_every
    return pd.DataFrame(rows, columns=["frame", "t", "side", "u", "z", "area"])


def game_video(game: Path) -> Path:
    """game.json 'video', relative to game.json."""
    g = json.loads(Path(game).read_text(encoding="utf-8"))
    v = Path(g.get("video", ""))
    return v if v.is_absolute() else Path(game).parent / v


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner rim-scan", description="Ball-sized movers in the air at each rim")
    ap.add_argument("--run", required=True, help="run folder with camera.npz")
    ap.add_argument("--game", help="game.json (its 'video' is read)")
    ap.add_argument("--video", help="video file (default: game.json 'video')")
    ap.add_argument("--out", help="default: RUN/rim_scan.pkl")
    ap.add_argument("--step", type=int, default=2, help="read every n-th video frame (default 2: 30 of 60 fps)")
    ap.add_argument("--from", dest="t0", type=float, help="start (s), to try a slice")
    ap.add_argument("--to", dest="t1", type=float, help="end (s)")
    a = ap.parse_args(argv)
    run = Path(a.run)
    video = Path(a.video) if a.video else game_video(a.game) if a.game else None
    if video is None or not video.is_file():
        raise SystemExit(f"video not found: {video} (pass --video or --game)")
    out = Path(a.out) if a.out else run / "rim_scan.pkl"
    cam = dict(np.load(run / "camera.npz"))
    cap = cv2.VideoCapture(str(video))
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720)
    rng = (a.t0 or 0.0, a.t1 if a.t1 is not None else 1e9) if (a.t0 is not None or a.t1 is not None) else None
    df = scan_rims(cap, cam, size, step=a.step, t_range=rng)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(out)
    print(f"rim-scan: {len(df)} blobs -> {out}")


if __name__ == "__main__":
    main()
