"""Review material for a movement session: skeleton overlay reel, key-frame sheets, label strips, review briefs.

usage: hoop-tape-miner move-sheets <movement folder> [--group-size 8] [--force]

Writes (needs move-scan first):
  <media>/reel.overlay.mp4         the reel with the tracked skeleton and each segment's label; side-view segments also
                                   get trunk / shin angles and TD (touchdown) tags. movement.json video_overlay points
                                   here, so clips and film use it.
  <run>/move_review/keys_<id>.jpg  crops of the player from the source video: for a layup every 0.1 s from 1.5 s before
                                   the release to 0.8 s after, else 24 frames across the segment; skeleton drawn
  <run>/move_review/strip_<id>.jpg side-view segments only: every frame (up to 120) of the 1.5 s before take-off (layup)
                                   or the first 2 s, numbered by source time, for the hand-labelled contact check
  <run>/move_review/brief_<g>.md   one review brief per group of segments (prompts/movement_review_brief.md)
  <run>/move_review/manifest.json  groups, their segments and sheets
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import movement as M
from . import train_scan as S
from . import train_sheets as TS
from . import training as T

BRIEF = Path(__file__).resolve().parents[2] / "prompts" / "movement_review_brief.md"
KEY_N, KEY_STEP, KEY_BEFORE, KEY_AFTER = 24, 0.1, 1.5, 0.8
STRIP_MAX, TILE_H, COLS = 120, 300, 6
BONES = [(T.L_SH, T.R_SH), (T.L_HIP, T.R_HIP), (T.L_SH, T.L_HIP), (T.R_SH, T.R_HIP), (T.L_SH, T.L_EL), (T.L_EL, T.L_WR),
         (T.R_SH, T.R_EL), (T.R_EL, T.R_WR), (T.L_HIP, T.L_KN), (T.L_KN, T.L_AN), (T.R_HIP, T.R_KN), (T.R_KN, T.R_AN)]
LEFT = {T.L_SH, T.L_EL, T.L_WR, T.L_HIP, T.L_KN, T.L_AN}
COL_L, COL_R, COL_C = (255, 170, 40), (40, 120, 255), (60, 230, 60)  # BGR: left blue, right orange, trunk green


def draw_overlay(frame: np.ndarray, kp: np.ndarray, conf: np.ndarray, marks: dict | None = None,
                 thick: int = 2) -> np.ndarray:
    """Draw the skeleton (left side blue, right orange) on a copy of frame. marks: {"angles": True} writes the trunk
    lean (and shin angle of a planted foot) from vertical, {"tags": ["TD L"]} writes tags under the feet."""
    import cv2
    img = frame.copy()
    marks = marks or {}
    ok = conf >= T.KP_MIN
    pt = lambda i: (int(round(kp[i, 0])), int(round(kp[i, 1])))
    for a, b in BONES:
        if ok[a] and ok[b] and np.isfinite(kp[[a, b]]).all():
            col = COL_C if (a in LEFT) != (b in LEFT) else (COL_L if a in LEFT else COL_R)
            cv2.line(img, pt(a), pt(b), col, thick, cv2.LINE_AA)
    for i in range(17):
        if ok[i] and np.isfinite(kp[i]).all() and i >= T.L_SH:
            cv2.circle(img, pt(i), thick + 1, (255, 255, 255), -1, cv2.LINE_AA)
    if marks.get("angles"):
        sh, hp = kp[[T.L_SH, T.R_SH]].mean(0), kp[[T.L_HIP, T.R_HIP]].mean(0)
        if ok[[T.L_SH, T.R_SH, T.L_HIP, T.R_HIP]].all() and np.isfinite([sh, hp]).all():
            lean = abs(np.degrees(np.arctan2(sh[0] - hp[0], hp[1] - sh[1])))
            cv2.putText(img, f"trunk {lean:.0f}", (int(hp[0]) + 8, int(hp[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        COL_C, 1, cv2.LINE_AA)
    for k, tag in enumerate(marks.get("tags") or []):
        x = int(np.nanmean(kp[[T.L_AN, T.R_AN], 0])) if np.isfinite(kp[[T.L_AN, T.R_AN], 0]).any() else 10
        y = int(np.nanmax(kp[[T.L_AN, T.R_AN], 1])) + 18 + 16 * k if np.isfinite(kp[[T.L_AN, T.R_AN], 1]).any() else 30
        cv2.putText(img, tag, (x - 20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return img


# ---- times -------------------------------------------------------------------------------------------------

def key_times(seg: dict, g: dict) -> list[float]:
    """Source times of the key-frame sheet: around the release for a layup, else KEY_N across the segment."""
    a, b = M.seg_seconds(seg)
    rel = g.get("release")
    if seg["kind"] == "layup" and rel is not None:
        ts = np.arange(rel - KEY_BEFORE, rel + KEY_AFTER + 1e-9, KEY_STEP * M.slowmo(seg))
        return [round(float(x), 3) for x in ts if a <= x <= b]
    return [round(float(x), 3) for x in np.linspace(a, b, KEY_N)]


def strip_times(seg: dict, g: dict, pose_t: np.ndarray) -> list[float]:
    """Pose frame times for the hand-label strip (side view only): the 1.5 s before take-off for a layup (take-off
    from the scan, else the release), else the first 2 s; at most STRIP_MAX evenly spaced frames."""
    if seg["view"] != "side" or not len(pose_t):
        return []
    lay = g.get("layup") or {}
    end = lay.get("takeoff_t") or g.get("release")
    k = M.slowmo(seg)
    if seg["kind"] == "layup" and end is not None:
        lo, hi = end - 1.5 * k, end + 0.1 * k
    else:
        lo, hi = float(pose_t[0]), float(pose_t[0]) + 2.0 * k
    ts = pose_t[(pose_t >= lo - 1e-9) & (pose_t <= hi + 1e-9)]
    if len(ts) > STRIP_MAX:
        ts = ts[np.linspace(0, len(ts) - 1, STRIP_MAX).round().astype(int)]
    return [round(float(x), 4) for x in ts]


def read_frames(video: Path, times: list[float]) -> dict[float, np.ndarray]:
    """Frames of the source video nearest each requested time (one pass over the window)."""
    if not times:
        return {}
    import cv2
    cap = cv2.VideoCapture(str(video))
    src = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    want = sorted(times)
    got: dict[float, tuple[float, np.ndarray]] = {}
    for t, f in S.frames(video, src, max(0.0, want[0] - 1 / src), want[-1] + 1 / src):
        for w in want:
            if abs(t - w) <= 0.51 / src and (w not in got or abs(t - w) < abs(got[w][0] - w)):
                got[w] = (t, f)
    return {w: f for w, (_, f) in got.items()}


def nearest(pose: dict, t: float, tol: float) -> int | None:
    if not len(pose["t"]):
        return None
    i = int(np.argmin(np.abs(pose["t"] - t)))
    return i if abs(pose["t"][i] - t) <= tol else None


# ---- sheets ------------------------------------------------------------------------------------------------

def tile(frame, pose, i, caption, marks=None, h=TILE_H):
    """A crop of the player (skeleton drawn) at pose index i, captioned."""
    if i is not None:
        frame = draw_overlay(frame, pose["kp"][i], pose["conf"][i], marks, thick=max(1, frame.shape[0] // 500))
        box = TS.player_box(pose, float(pose["t"][i]))
    else:
        box = TS.player_box(pose, float(pose["t"][0])) if len(pose["t"]) else None
    if box is None:
        img = frame
    else:
        x0, y0, x1, y1 = box
        cx, w = (x0 + x1) / 2, max(x1 - x0, (y1 - y0) * 0.75)
        img = TS.crop(frame, cx - w / 2, y0, cx + w / 2, y1)
    return TS.label(TS.resize_h(img, h), caption, 0.5)


def grid(tiles: list, cols: int = COLS):
    rows = [TS.hstack(tiles[k:k + cols]) for k in range(0, len(tiles), cols)]
    return TS.vstack(rows) if rows else None


def contact_tags(g: dict, t: float, tol: float) -> list[str]:
    return [f"TD {c['foot']}" for c in g.get("contacts") or [] if abs(c["on"] - t) <= tol]


def key_sheet(seg: dict, g: dict, pose: dict, out: Path) -> Path | None:
    times = key_times(seg, g)
    frames = read_frames(Path(seg["source"]), times)
    tol = 0.6 / max(float(seg.get("scan_fps") or 30), 1)
    side = seg["view"] == "side"
    rel = g.get("release")
    tiles = []
    for t in times:
        if t not in frames:
            continue
        i = nearest(pose, t, tol)
        cap = T.mmss(t) + (f" ({t - rel:+.1f})" if rel is not None else "")
        tiles.append(tile(frames[t], pose, i, cap, {"angles": side, "tags": contact_tags(g, t, tol) if side else []}))
    img = grid(tiles)
    if img is None:
        return None
    TS.save(img, out)
    return out


def strip_sheet(seg: dict, g: dict, pose: dict, out: Path) -> Path | None:
    times = strip_times(seg, g, pose["t"])
    if not times:
        return None
    frames = read_frames(Path(seg["source"]), times)
    tiles = [tile(frames[t], pose, nearest(pose, t, 1e-3), f"{t:.3f}", h=220) for t in times if t in frames]
    img = grid(tiles, cols=10)
    if img is None:
        return None
    TS.save(img, out)
    return out


# ---- overlay reel --------------------------------------------------------------------------------------------

def reel_transform(seg: dict, size) -> tuple[float, float, float, float, float]:
    """(scale, offset x, offset y, crop x, crop y): source px -> reel px, as move-new letterboxed the segment."""
    sw, sh = float(size[0]), float(size[1])
    cx, cy, cw, ch = (seg.get("crop") or [0, 0, 1, 1])
    cx, cy, cw, ch = cx * sw, cy * sh, cw * sw, ch * sh
    s = min(M.REEL_W / cw, M.REEL_H / ch)
    return s, (M.REEL_W - cw * s) / 2, (M.REEL_H - ch * s) / 2, cx, cy


def overlay_reel(m: dict, folder: Path, run: Path, out: Path) -> Path:
    """Draw every segment's skeleton and label on the reel; writes `out` (H.264)."""
    import cv2
    reel = M.path(folder, m, "video", "reel.mp4")
    segs = m["segments"]
    poses, gaits = {}, {}
    for s in segs:
        p = run / "seg" / f"{s['id']}.npz"
        if p.exists():
            z = np.load(p)
            poses[s["id"]] = {k: z[k] for k in z.files}
        gp = run / "gait" / f"{s['id']}.json"
        gaits[s["id"]] = json.loads(gp.read_text(encoding="utf8")) if gp.exists() else {}
    cap = cv2.VideoCapture(str(reel))
    fps = cap.get(cv2.CAP_PROP_FPS) or M.REEL_FPS
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "overlay.avi"
        wr = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"MJPG"), fps, (M.REEL_W, M.REEL_H))
        i = 0
        while True:
            ok, f = cap.read()
            if not ok:
                break
            rt = i / fps
            i += 1
            seg = next((s for s in segs if s["reel_from"] - 1e-6 <= rt < s["reel_to"]), segs[-1])
            a, _ = M.seg_seconds(seg)
            st = a + (rt - seg["reel_from"])
            pose, g = poses.get(seg["id"]), gaits.get(seg["id"], {})
            side = seg["view"] == "side"
            if pose is not None:
                j = nearest(pose, st, 0.6 / max(float(seg.get("scan_fps") or 30), 1))
                if j is not None:
                    sc, ox, oy, cx, cy = reel_transform(seg, pose["size"])
                    kp = (pose["kp"][j] - (cx, cy)) * sc + (ox, oy)
                    tol = 0.5 / fps * 3
                    f = draw_overlay(f, kp, pose["conf"][j], {"angles": side,
                                                             "tags": contact_tags(g, st, tol) if side else []})
            TS.label(f, f"{seg['id']}  {seg['kind']} / {seg['view']}  {T.mmss(st)}", 0.7)
            wr.write(f)
        wr.release()
        cap.release()
        subprocess.run([os.environ.get("FFMPEG", "ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(raw),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(out)], check=True)
    return out


# ---- briefs ------------------------------------------------------------------------------------------------

def groups(segments: list[dict], size: int = 8) -> list[list[dict]]:
    """Review groups of at most `size` segments, as even as possible, in reel order."""
    n = len(segments)
    if not n:
        return []
    k = -(-n // size)
    per = -(-n // k)
    return [segments[i:i + per] for i in range(0, n, per)]


def gait_line(g: dict) -> str:
    if g.get("metrics", "x") is None:
        return "review only (game camera)"
    if not g.get("measurable"):
        return (f"pose tracked {g.get('visible_share', 0):.0%} of frames; not a side view, so no running or layup "
                "numbers (2D angles from this view are not valid)")
    c = g.get("clip") or {}
    parts = [f"{c.get('n_steps', 0)} steps"]
    if c.get("cadence_spm"):
        parts.append(f"cadence about {c['cadence_spm']:.0f}/min")
    for k in ("trunk_lean", "shin", "touchdown_ahead"):
        if c.get(k):
            parts.append(f"{k} first3 about {c[k]['first3']:.2f}")
    if g.get("layup"):
        lay = g["layup"]
        parts += [f"{k} {lay[k]}" for k in ("penultimate_ratio", "hip_drop", "takeoff_knee", "free_knee") if lay.get(k) is not None]
    return "; ".join(parts) + " (unchecked until the label check passes)"


def write_brief(folder: Path, m: dict, out: Path, name: str, segs: list[dict], sheets: dict, gaits: dict) -> Path:
    text = re.sub(r"\A(# .*\n)\n<!--.*?-->\n", r"\1", BRIEF.read_text(encoding="utf8"), flags=re.S)
    rows = []
    for s in segs:
        sh = sheets.get(s["id"], {})
        rows.append(f"### {s['id']} · {s['kind']} · view {s['view']}\n"
                    f"- source {Path(s['source']).name} {s['from']}-{s['to']} (reel {T.mmss(s['reel_from'])}-"
                    f"{T.mmss(s['reel_to'])}); note: {s.get('note') or '-'}\n"
                    f"- key frames: {sh.get('keys') or '(none: game camera, watch the overlay reel at the reel times)'}\n"
                    f"- pose numbers: {gait_line(gaits.get(s['id'], {}))}")
    vals = {
        "session": str(folder), "player": f"{m.get('name') or ''} #{m.get('player')}".strip(),
        "plan": m.get("plan") or "(not given)", "group": name, "reel": str(M.path(folder, m, "video_overlay", "reel.mp4")),
        "who": (f"others are in frame. The player is: {m['look']}. If the skeleton or crop follows someone else, list "
                "those stretches in `wrong_person` and judge only frames where the player is clear (`identity_ok: "
                "false` when that is most of the window)."
                if m.get("look") else "only the player should be in frame."),
        "segments": "\n\n".join(rows), "json": str(out / f"review_{name}.json"), "memo": str(out / f"memo_{name}.md"),
    }
    for k, v in vals.items():
        text = text.replace("{{" + k + "}}", v)
    p = out / f"brief_{name}.md"
    p.write_text(text, encoding="utf8")
    return p


def build(folder: Path, group_size: int = 8, force: bool = False) -> dict:
    m = M.load(folder)
    run = M.path(folder, m, "run", "run")
    out = run / "move_review"
    out.mkdir(parents=True, exist_ok=True)
    sheets, gaits = {}, {}
    for s in m["segments"]:
        gp = run / "gait" / f"{s['id']}.json"
        if not gp.exists():
            sys.exit(f"[move-sheets] no {gp}: run move-scan first")
        g = gaits[s["id"]] = json.loads(gp.read_text(encoding="utf8"))
        npz = run / "seg" / f"{s['id']}.npz"
        sheets[s["id"]] = {}
        if not npz.exists():
            continue
        z = np.load(npz)
        pose = {k: z[k] for k in z.files}
        kp_, st_ = out / f"keys_{s['id']}.jpg", out / f"strip_{s['id']}.jpg"
        if force or not kp_.exists():
            key_sheet(s, g, pose, kp_)
        if s["view"] == "side" and (force or not st_.exists()):
            strip_sheet(s, g, pose, st_)
        sheets[s["id"]] = {k: str(p) for k, p in (("keys", kp_), ("strip", st_)) if p.exists()}
    ov = M.path(folder, m, "video", "reel.mp4").with_name("reel.overlay.mp4")
    if force or not ov.exists() or ov.stat().st_mtime < M.path(folder, m, "video", "reel.mp4").stat().st_mtime:
        print("[move-sheets] drawing the overlay reel", flush=True)
        overlay_reel(m, folder, run, ov)
    m["video_overlay"] = str(ov)
    M.save(folder, m)
    man = {"groups": []}
    for k, segs in enumerate(groups(m["segments"], group_size), 1):
        name = f"g{k}"
        b = write_brief(folder, m, out, name, segs, sheets, gaits)
        man["groups"].append(dict(name=name, segments=[s["id"] for s in segs], brief=str(b),
                                  json=str(out / f"review_{name}.json"),
                                  sheets={s["id"]: sheets.get(s["id"], {}) for s in segs}))
    man["label_segments"] = [s["id"] for s in m["segments"] if sheets.get(s["id"], {}).get("strip")]
    (out / "manifest.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf8")
    print(f"[move-sheets] {len(man['groups'])} briefs, {sum(1 for v in sheets.values() if v.get('keys'))} key sheets, "
          f"{len(man['label_segments'])} label strips -> {out}")
    return man


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner move-sheets", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="movement session folder (with movement.json)")
    ap.add_argument("--group-size", type=int, default=8, help="segments per review brief (default 8)")
    ap.add_argument("--force", action="store_true", help="redraw sheets and the overlay reel")
    a = ap.parse_args(argv)
    if not M.is_movement(Path(a.folder)):
        sys.exit(f"no movement.json in {a.folder}")
    build(Path(a.folder), a.group_size, a.force)


if __name__ == "__main__":
    main()
