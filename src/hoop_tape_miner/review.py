"""Possession review sheets: annotated frame grids used to label events (shots, makes,
turnovers, play types) with a vision-language reviewer (Claude or a local VLM).

Each sheet = 3x2 frames at `--every` seconds, players outlined in team colour with the
recognised jersey number, timestamp burnt in. A manifest.json lists sheets per possession.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .game_config import hex_to_bgr, load_game, team_hex

BGR = {"us": hex_to_bgr(team_hex({}, "us")), "them": hex_to_bgr(team_hex({}, "them")), "ref": (90, 90, 90)}


def use_game(game: dict):
    """Outline colours from game.json us.hex / them.hex (neutral defaults when missing)."""
    for side in ("us", "them"):
        BGR[side] = hex_to_bgr(team_hex(game, side))


def annotate(frame, dets, numbers):
    out = frame.copy()
    for _, r in dets.iterrows():
        c = BGR.get(r.team, (200, 200, 200))
        cv2.rectangle(out, (int(r.x1), int(r.y1)), (int(r.x2), int(r.y2)), c, 2)
        n = numbers.get(int(r.track))
        if n and r.team in ("us", "them"):
            lab = f"#{n}"
            cv2.putText(out, lab, (int(r.x1), int(r.y1) - 4), 0, 0.6, (0, 0, 0), 4)
            cv2.putText(out, lab, (int(r.x1), int(r.y1) - 4), 0, 0.6, (255, 255, 255), 2)
    return out


BALL_BGR = (0, 165, 255)  # orange trail
ATTEMPT_BGR = (255, 255, 0)  # cyan arc + rim ring


def draw_ball_trail(img, pts, color=BALL_BGR):
    """Ball trail in place: pts = [(x, y), ...] oldest first (image px, NaN rows skipped); the newest point gets a
    ring. Returns img."""
    p = [(int(round(x)), int(round(y))) for x, y in pts if np.isfinite(x) and np.isfinite(y)]
    for i in range(1, len(p)):
        cv2.line(img, p[i - 1], p[i], color, 1 + 2 * i // len(p), cv2.LINE_AA)
    if p:
        cv2.circle(img, p[-1], 9, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.circle(img, p[-1], 9, color, 2, cv2.LINE_AA)
    return img


def draw_attempt(img, arc_px, rim_px, text, color=ATTEMPT_BGR):
    """CV shot-attempt marker in place: the arc (image px), a ring on the rim and a label such as
    'CV attempt? likely miss'. Returns img."""
    p = [(int(round(x)), int(round(y))) for x, y in arc_px if np.isfinite(x) and np.isfinite(y)]
    for a, b in zip(p, p[1:]):
        cv2.line(img, a, b, color, 2, cv2.LINE_AA)
    if rim_px is not None and np.isfinite(rim_px).all():
        c = (int(round(rim_px[0])), int(round(rim_px[1])))
        cv2.circle(img, c, 22, color, 2, cv2.LINE_AA)
        org = (max(0, c[0] - 150), max(20, c[1] - 30))
        cv2.putText(img, text, org, 0, 0.8, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, text, org, 0, 0.8, color, 2, cv2.LINE_AA)
    return img


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--pad", type=float, default=2.0, help="seconds after possession end")
    ap.add_argument("--game", help="game.json (team colours); default: neutral colours")
    args = ap.parse_args(argv)
    use_game(load_game(args.game))
    run = Path(args.run)
    tr = pd.read_pickle(run / "tracks.pkl")
    poss = pd.read_pickle(run / "possessions.pkl")
    numbers = {int(k): v for k, v in json.loads((run / "player_numbers.json").read_text()).items()}
    out_dir = run / "review"
    out_dir.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    by_frame = {f: g for f, g in tr.groupby("frame")}
    analysed = np.array(sorted(by_frame))
    manifest = []
    for pid, p in poss.iterrows():
        ts = np.arange(p.start, p.end + args.pad, args.every)
        tiles = []
        for t in ts:
            fi = int(round(t * fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, f = cap.read()
            if not ok:
                continue
            near = analysed[np.abs(analysed - fi).argmin()]
            img = annotate(f, by_frame[near], numbers) if abs(near - fi) <= 6 else f
            img = cv2.resize(img, (640, 360))
            cv2.rectangle(img, (0, 0), (150, 26), (0, 0, 0), -1)
            m, s = divmod(t, 60)
            cv2.putText(img, f"{int(m):02d}:{s:04.1f}", (6, 19), 0, 0.65, (0, 255, 255), 2)
            tiles.append(img)
        sheets = []
        for k in range(0, len(tiles), 6):
            chunk = tiles[k:k + 6] + [np.zeros_like(tiles[0])] * (6 - len(tiles[k:k + 6]))
            sheet = np.vstack([np.hstack(chunk[:3]), np.hstack(chunk[3:])])
            path = out_dir / f"p{pid:03d}_{k // 6}.jpg"
            cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
            sheets.append(str(path))
        manifest.append(dict(pid=int(pid), start=float(p.start), end=float(p.end), side=p.side,
                             offence=p.offence, period=int(p.period), sheets=sheets))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(len(manifest), "possessions,", sum(len(m["sheets"]) for m in manifest), "sheets")


if __name__ == "__main__":
    main()
