"""Scan a movement session: the player's pose in every segment at its native frame rate, then 2D gait metrics.

usage: hoop-tape-miner move-scan <movement folder> [--force] [--only S01,S03]

For each segment of movement.json, runs YOLO pose (and the ball detector for layup and dribble-sprint segments) on
the segment's window of its *source* video at scan_fps (native, capped at 120 real frames per second), follows the
player (segment "seed", else the largest person) and writes to the session's run folder:
  seg/<id>.npz     t (source s), kp, conf, box, ball, size; reused on the next run (--force to redo)
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


def scan_segments(folder: Path, force: bool = False, only: list[str] | None = None, scanner=None) -> list[str]:
    """Pose + metrics for the segments of a movement session; returns the ids that were scanned (not reused)."""
    scanner = scanner or S.scan
    m = M.load(folder)
    run = M.path(folder, m, "run", "run")
    (run / "seg").mkdir(parents=True, exist_ok=True)
    (run / "gait").mkdir(parents=True, exist_ok=True)
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
            npz = run / "seg" / f"{sid}.npz"
            if npz.exists() and not force:
                z = np.load(npz)
                d = {k: z[k] for k in z.files}
            else:
                a, b = M.seg_seconds(seg)
                print(f"[move-scan] {sid} {seg['kind']}/{seg['view']} {seg['from']}-{seg['to']} at "
                      f"{seg.get('scan_fps')} fps", flush=True)
                raw = scanner(Path(seg["source"]), float(seg.get("scan_fps") or 30), seg["kind"] in BALL_KINDS, a, b)
                d = S.pick(raw, tuple(seg["seed"]) if seg.get("seed") else None, "player")
                np.savez_compressed(npz, **d)
                scanned.append(sid)
            g = metrics(seg, d)
        gpath.write_text(json.dumps(g, indent=1) + "\n", encoding="utf8")
        allg.append(g)
    (run / "gait.json").write_text(json.dumps(allg, indent=1) + "\n", encoding="utf8")
    n_steps = sum(len(g.get("steps") or []) for g in allg)
    print(f"[move-scan] {len(allg)} segments ({len(scanned)} scanned, the rest reused), {n_steps} steps found")
    return scanned


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner move-scan", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="movement session folder (with movement.json)")
    ap.add_argument("--force", action="store_true", help="re-run pose even where seg/<id>.npz exists")
    ap.add_argument("--only", help="comma-separated segment ids")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    if not M.is_movement(folder):
        sys.exit(f"no movement.json in {folder}")
    scan_segments(folder, a.force, a.only.split(",") if a.only else None)


if __name__ == "__main__":
    main()
