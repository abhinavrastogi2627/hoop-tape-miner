"""Review sheets for a training session: what the film-review agent looks at to judge every rep.

usage: hoop-tape-miner train-sheets <session folder> --probe
       hoop-tape-miner train-sheets <session folder> [--reps-per-part 50] [--force]

--probe writes <run>/train_review/rim_probe.jpg: four frames across the session with a 10 x 10 grid (x / y frame
fractions), so the agent can set session.json `rim` (rim boxes) and `rim_checked`.

Without --probe (needs rim_checked) it writes to <run>/train_review/:
  overview_<NN>.jpg   one frame every 10 s (what drill is going on, where the player stands)
  reps_<NN>.jpg       per rep candidate: set / release / follow-through crops of the player, a filmstrip of the
                      rim every 0.2 s from +0.3 s to +2.1 s after the release plus one wide frame at +0.8 s (or
                      three wide frames without a rim box)
  dribble_<NN>.jpg    per dribble segment: six crops of the player across it
  manifest.json       parts (time ranges) with their sheets and candidates
  brief_part<N>.md    the review brief per part, from prompts/training_review_brief.md
Once review_part*.json exist it refuses to rebuild unless --force (the parts may change under the reviews).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

from . import training as T

REPO = Path(__file__).resolve().parents[2]
BRIEF = REPO / "prompts" / "training_review_brief.md"
OVERVIEW_EVERY_S = 10
OVERVIEW_PER_SHEET = 12
REPS_PER_SHEET = 5
DRIBBLES_PER_SHEET = 4
ROW_H = 300
RIM_OFFSETS = [0.3 + 0.2 * k for k in range(10)]
WIDE_OFFSETS = [0.6, 1.2, 1.8]
RIM_H = 170  # rim filmstrip tile height
CHECK_OFFSET = 0.8  # one wide frame with the rim box: shooter and rim together
INK, PAPER = (30, 30, 30), (250, 250, 248)


# ---- frames ------------------------------------------------------------------------------------------------

def grab(video: Path, jobs: list[tuple[float, object, callable]]) -> dict:
    """Read the video once; for each job (t, key, fn) call fn(frame at t) and keep only its (small) result."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    want: dict[int, list] = {}
    for t, key, fn in jobs:
        want.setdefault(min(max(int(round(t * fps)), 0), max(n - 1, 0)), []).append((key, fn))
    out, i, last = {}, 0, max(want) if want else -1
    while i <= last and cap.grab():
        if i in want:
            ok, f = cap.retrieve()
            if ok:
                for key, fn in want[i]:
                    out[key] = fn(f)
        i += 1
    cap.release()
    return out


def resize_h(img, h: int):
    import cv2
    return cv2.resize(img, (max(1, round(img.shape[1] * h / img.shape[0])), h), interpolation=cv2.INTER_AREA)


def crop(f, x0, y0, x1, y1):
    """Crop with padding where the box leaves the frame."""
    H, W = f.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in (x0, y0, x1, y1))
    out = np.full((max(y1 - y0, 1), max(x1 - x0, 1), 3), 40, np.uint8)
    sx0, sy0, sx1, sy1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = f[sy0:sy1, sx0:sx1]
    return out


def label(img, text: str, scale: float = 0.55):
    import cv2
    (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    cv2.rectangle(img, (0, 0), (w + 8, h + 10), (0, 0, 0), -1)
    cv2.putText(img, text, (4, h + 4), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def hstack(imgs, gap: int = 6):
    h = max(i.shape[0] for i in imgs)
    cols = []
    for k, i in enumerate(imgs):
        pad = np.full((h, i.shape[1], 3), PAPER, np.uint8)
        pad[:i.shape[0]] = i
        cols += [pad] + ([np.full((h, gap, 3), PAPER, np.uint8)] if k < len(imgs) - 1 else [])
    return np.hstack(cols)


def vstack(imgs, gap: int = 10):
    w = max(i.shape[1] for i in imgs)
    rows = []
    for k, i in enumerate(imgs):
        pad = np.full((i.shape[0], w, 3), PAPER, np.uint8)
        pad[:, :i.shape[1]] = i
        rows += [pad] + ([np.full((gap, w, 3), PAPER, np.uint8)] if k < len(imgs) - 1 else [])
    return np.vstack(rows)


def text_panel(lines: list[str], w: int = 230, h: int = ROW_H):
    import cv2
    img = np.full((h, w, 3), PAPER, np.uint8)
    for k, line in enumerate(lines):
        cv2.putText(img, line, (8, 30 + 26 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.62 if k else 0.8, INK, 2 if k == 0 else 1, cv2.LINE_AA)
    return img


def save(img, path: Path):
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 82])


# ---- geometry ----------------------------------------------------------------------------------------------

def rim_at(s: dict, t: float, size: tuple[int, int]):
    """Rim box in px (x, y, w, h) at time t from session.json `rim` ([{from, box}], fractions); None if not visible."""
    cur = None
    for r in sorted(s.get("rim") or [], key=lambda r: T.seconds(r.get("from", 0))):
        if T.seconds(r.get("from", 0)) <= t + 1e-6:
            cur = r.get("box")
    if not cur:
        return None
    W, H = size
    return cur[0] * W, cur[1] * H, cur[2] * W, cur[3] * H


def rim_window(box):
    """Area around the rim: 3 rim widths wide, from 2.5 widths above the rim to 1.5 below (ball, rim, net)."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    return cx - 1.5 * w, cy - 2.5 * w, cx + 1.5 * w, cy + 1.5 * w


def player_box(pose: dict, t: float):
    """Player box at the pose frame nearest t, widened for raised arms and the ball; None when not seen."""
    i = int(np.argmin(np.abs(pose["t"] - t)))
    b = pose["box"][i]
    if not np.isfinite(b).all():
        ok = np.where(np.isfinite(pose["box"][:, 0]))[0]
        if not len(ok):
            return None
        b = pose["box"][ok[np.argmin(np.abs(pose["t"][ok] - t))]]
    x0, y0, x1, y1 = b
    w, h = x1 - x0, y1 - y0
    return x0 - 0.35 * w, y0 - 0.45 * h, x1 + 0.35 * w, y1 + 0.08 * h


# ---- sheets ------------------------------------------------------------------------------------------------

def probe(video: Path, out: Path, duration: float):
    import cv2

    def grid(f):
        f = f.copy()
        H, W = f.shape[:2]
        for k in range(1, 10):
            cv2.line(f, (W * k // 10, 0), (W * k // 10, H), (0, 255, 255), 1)
            cv2.line(f, (0, H * k // 10), (W, H * k // 10), (0, 255, 255), 1)
            cv2.putText(f, f".{k}", (W * k // 10 + 3, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(f, f".{k}", (3, H * k // 10 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        return resize_h(f, 540)

    times = [duration * q for q in (0.1, 0.35, 0.6, 0.85)]
    got = grab(video, [(t, t, grid) for t in times])
    tiles = [label(got[t], T.mmss(t), 0.8) for t in times if t in got]
    save(vstack([hstack(tiles[:2]), hstack(tiles[2:])]), out)
    print(f"[train-sheets] wrote {out}")


def build(folder: Path, s: dict, run: Path, video: Path, reps_per_part: int = 50) -> dict:
    out = run / "train_review"
    out.mkdir(parents=True, exist_ok=True)
    z = np.load(run / "pose.npz")
    pose = {k: z[k] for k in z.files}
    size = tuple(int(v) for v in pose["size"])
    reps = json.loads((run / "reps.json").read_text(encoding="utf8"))
    drib = json.loads((run / "dribble.json").read_text(encoding="utf8"))
    duration = float(pose["t"][-1]) if len(pose["t"]) else 0.0

    jobs = []
    over_t = list(np.arange(0, duration, OVERVIEW_EVERY_S))
    for t in over_t:
        jobs.append((t, ("o", t), lambda f, t=t: label(resize_h(f, 240), T.mmss(t))))
    for r in reps:
        t = r["t"]
        for tag, dt in (("set", -0.5), ("rel", 0.0), ("fol", 0.35)):
            b = player_box(pose, t + dt)
            if b is not None:
                jobs.append((t + dt, (r["id"], tag), lambda f, b=b, tag=tag: label(resize_h(crop(f, *b), ROW_H), tag)))
        rim = rim_at(s, t, size)
        if rim:
            win = rim_window(rim)
            for k, dt in enumerate(RIM_OFFSETS):
                jobs.append((t + dt, (r["id"], f"rim{k}"), lambda f, win=win, dt=dt: label(resize_h(crop(f, *win), RIM_H), f"+{dt:.1f}", 0.45)))
            jobs.append((t + CHECK_OFFSET, (r["id"], "wide0"),
                         lambda f: label(resize_h(f, ROW_H), f"+{CHECK_OFFSET:.1f}s")))
        else:
            for k, dt in enumerate(WIDE_OFFSETS):
                jobs.append((t + dt, (r["id"], f"wide{k}"), lambda f, dt=dt: label(resize_h(f, ROW_H), f"+{dt:.1f}s")))
    for d in drib:
        for k, t in enumerate(np.linspace(d["from"], d["to"], 6)):
            b = player_box(pose, t)
            if b is not None:
                jobs.append((t, (f"D{d['from']}", k), lambda f, b=b, t=t: label(resize_h(crop(f, *b), 240), T.mmss(t))))
    print(f"[train-sheets] reading {len(jobs)} frames", flush=True)
    got = grab(video, jobs)

    def rep_row(r):
        m = r
        lines = [r["id"], T.mmss(r["t"]), f"hint {r['hint']}  hand {r['hand']}{' 2h' if r.get('two_hands') else ''}",
                 f"lift {m.get('lift')}", f"knee bend {m.get('knee_bend')}", f"elbow rel {m.get('elbow_release')}",
                 f"travel {m.get('travel')}", "rim box" if rim_at(s, r["t"], size) else "NO rim box"]
        cells = [text_panel(lines)] + [got[(r["id"], tag)] for tag in ("set", "rel", "fol") if (r["id"], tag) in got]
        rim = [got[(r["id"], f"rim{k}")] for k in range(len(RIM_OFFSETS)) if (r["id"], f"rim{k}") in got]
        if rim:
            cells.append(vstack([hstack(rim[:5], 3), hstack(rim[5:], 3)], 6))
        cells += [got[(r["id"], f"wide{k}")] for k in range(len(WIDE_OFFSETS)) if (r["id"], f"wide{k}") in got]
        return hstack(cells)

    # parts: equal numbers of candidates, cut halfway between neighbouring reps
    n_parts = max(1, math.ceil(len(reps) / reps_per_part))
    cuts = [0.0]
    for p in range(1, n_parts):
        k = round(p * len(reps) / n_parts)
        cuts.append((reps[k - 1]["t"] + reps[k]["t"]) / 2)
    cuts.append(duration + 1)
    parts = []
    for p in range(n_parts):
        a, b = cuts[p], cuts[p + 1]
        sheets = []
        ot = [t for t in over_t if a <= t < b]
        for k in range(0, len(ot), OVERVIEW_PER_SHEET):
            tiles = [got[("o", t)] for t in ot[k:k + OVERVIEW_PER_SHEET] if ("o", t) in got]
            rows = [hstack(tiles[j:j + 4]) for j in range(0, len(tiles), 4)]
            name = f"overview_{p + 1}{k // OVERVIEW_PER_SHEET + 1:02d}.jpg"
            save(vstack(rows), out / name)
            sheets.append(name)
        pr = [r for r in reps if a <= r["t"] < b]
        for k in range(0, len(pr), REPS_PER_SHEET):
            name = f"reps_{p + 1}{k // REPS_PER_SHEET + 1:02d}.jpg"
            save(vstack([rep_row(r) for r in pr[k:k + REPS_PER_SHEET]], 14), out / name)
            sheets.append(name)
        pd = [d for d in drib if a <= d["from"] < b]
        for k in range(0, len(pd), DRIBBLES_PER_SHEET):
            rows = []
            for d in pd[k:k + DRIBBLES_PER_SHEET]:
                tiles = [got[(f"D{d['from']}", j)] for j in range(6) if (f"D{d['from']}", j) in got]
                head = text_panel([f"D {T.mmss(d['from'])}", f"to {T.mmss(d['to'])}", f"R {d['bounces']['R']} L {d['bounces']['L']}",
                                   f"{d['rate']}/s", f"ball {d.get('ball_seen')}"], 200, 240)
                rows.append(hstack([head] + tiles))
            name = f"dribble_{p + 1}{k // DRIBBLES_PER_SHEET + 1:02d}.jpg"
            save(vstack(rows, 14), out / name)
            sheets.append(name)
        parts.append(dict(part=p + 1, **{"from": T.mmss(a), "to": T.mmss(min(b, duration))}, sheets=sheets,
                          candidates=[r["id"] for r in pr], dribble=[[T.mmss(d["from"]), T.mmss(d["to"])] for d in pd]))
    manifest = dict(video=str(video), duration_s=round(duration, 1), rim=s.get("rim") or [], parts=parts)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf8")
    for part in parts:
        write_brief(folder, s, out, part, [r for r in reps if r["id"] in part["candidates"]], pd_of(drib, part))
    print(f"[train-sheets] {len(parts)} parts, {sum(len(p['sheets']) for p in parts)} sheets in {out}")
    return manifest


def pd_of(drib, part):
    a, b = T.seconds(part["from"]), T.seconds(part["to"])
    return [d for d in drib if a <= d["from"] < b + 1]


def candidate_table(reps: list[dict]) -> str:
    head = "| id | t | hint | hand | lift | knee bend | elbow at release | travel |\n|---|---|---|---|---|---|---|---|\n"
    return head + "".join(f"| {r['id']} | {T.mmss(r['t'])} | {r['hint']} | {r['hand']}{' (2 hands)' if r.get('two_hands') else ''} "
                          f"| {r.get('lift')} | {r.get('knee_bend')} | {r.get('elbow_release')} | {r.get('travel')} |\n"
                          for r in reps)


def write_brief(folder: Path, s: dict, out: Path, part: dict, reps: list[dict], drib: list[dict]):
    text = re.sub(r"\A(# .*\n)\n<!--.*?-->\n", r"\1", BRIEF.read_text(encoding="utf8"), flags=re.S)  # drop the template note
    vals = {
        "session": str(folder), "review": str(out), "part": str(part["part"]), "from": part["from"], "to": part["to"],
        "plan": s.get("plan") or "(not given)", "player": f"{s.get('name') or ''} #{s.get('player')}".strip(),
        "rim": "rim boxes set: rep sheets show a rim filmstrip" if s.get("rim") else
               "rim not visible in this session: rep sheets show three wide frames after the release instead of a rim filmstrip",
        "sheets": "\n".join(f"- {out / n}" for n in part["sheets"]) or "- (none)",
        "candidates": candidate_table(reps) if reps else "(no candidates in this part)",
        "dribble": "\n".join(f"- {T.mmss(d['from'])}-{T.mmss(d['to'])}: bounces R {d['bounces']['R']} / L {d['bounces']['L']}, "
                             f"{d['rate']}/s, ball seen {d.get('ball_seen')}" for d in drib) or "- (none detected)",
        "json": str(out / f"review_part{part['part']}.json"), "memo": str(out / f"memo_part{part['part']}.md"),
        "who": (f"others are in frame (a trainer or partner). The player is: {s['look']}. The crops follow whoever holds "
                "the ball, so some candidates are the other person: those are `not_a_rep` (write who in `form`), and "
                "dribbling, blocks and drills describe the player only." if s.get("look") else
                "only the player should be in frame; a candidate made by anyone else is `not_a_rep`."),
    }
    for k, v in vals.items():
        text = text.replace("{{" + k + "}}", v)
    (out / f"brief_part{part['part']}.md").write_text(text, encoding="utf8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner train-sheets", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="session folder (with session.json)")
    ap.add_argument("--probe", action="store_true", help="only write rim_probe.jpg (for setting session.json rim)")
    ap.add_argument("--reps-per-part", type=int, default=50, help="rep candidates per review part (default 50)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the sheets even when review_part*.json exist (their candidates may no longer match)")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    s = T.load_session(folder)
    run = T.session_path(folder, s, "run", "run")
    video = T.session_path(folder, s, "video", "session.mp4")
    if not (run / "pose.npz").exists():
        sys.exit(f"{run / 'pose.npz'} not found: run `hoop-tape-miner train-scan {folder}` first")
    if a.probe:
        z = np.load(run / "pose.npz")
        probe(video, run / "train_review" / "rim_probe.jpg", float(z["t"][-1]) if len(z["t"]) else 0.0)
        return
    if not s.get("rim_checked"):
        sys.exit("set session.json `rim` (or [] when the rim is not in view) and \"rim_checked\": true first; "
                 f"see `hoop-tape-miner train-sheets {folder} --probe`")
    reviewed = sorted((run / "train_review").glob("review_part*.json"))
    if reviewed and not a.force:
        sys.exit(f"{len(reviewed)} review_part*.json in {run / 'train_review'} were written against the current "
                 "sheets; rebuilding may move candidates between parts. Re-run with --force to rebuild anyway "
                 "(then review every part again).")
    build(folder, s, run, video, a.reps_per_part)


if __name__ == "__main__":
    main()
