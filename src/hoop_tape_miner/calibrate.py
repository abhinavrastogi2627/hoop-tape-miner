"""Court calibration keyframes (keyframes.json) for `extract --calib` / `recalib --calib`.

    hoop-tape-miner calibrate --video V --times 120,900 --out calib/                        # click points in a window
    hoop-tape-miner calibrate --video V --times 120,900 --out calib/ --grid                 # no GUI: grid_<t>.jpg to read
    hoop-tape-miner calibrate --video V --times 120,900 --out calib/ --points calib/points.json  # non-interactive
    ... --propagate 60,1040,1500       # also track the camera (backward and forward) and add keyframes at these times
    ... --detections run/detections.pkl  # mask player boxes (same video) while fitting and tracking

For each time (s): grab the frame, take >= 4 court landmarks (clicked, or from points.json),
fit a homography, snap it onto the painted lines (court.refine_homography), and save
kf_<t>.png + ov_<t>.jpg (overlay to eyeball). points.json:
    {"1020": [{"name": "L_lane_base_far", "px": [180, 355]}, {"court": [14, 15], "px": [1137, 282]}]}
`name` is one of LANDMARKS (court metres: x along the length from the left baseline, y from
the near/camera sideline); `court` gives raw coordinates. Interactive picks are saved to
<out>/points.json so a re-run can be non-interactive. Image paths in keyframes.json are
relative to the keyframes file; use `load_keyframes`/`load_bank` to read it.

Without a GUI (an agent): run --grid, read grid_<t>.jpg (pixel grid + numbered landmark map
below the frame), write points.json, run --points; each frame prints
`PASS|WEAK t=.. points=.. rms=.. support=.. median=..` and its worst points. A frame passes when
the line snap has support >= 120 and median < 3 px (the tracker's own acceptance) and every
given point lies within --max-point-err px of the snapped court. Only passing frames go to
keyframes.json (the interactive mode keeps all, as before); exit code 2 if any frame is weak
or missing, else 0.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .camera import CourtCameraTracker, KeyframeBank, _people_mask
from .court import CENTER_CIRCLE_R, FT_LINE, LANE_WIDTH, LENGTH, THREE_PT_SIDE, WIDTH, court_polylines, \
    draw_court_overlay, project, refine_homography

PASS_SUPPORT, PASS_MEDIAN, PASS_POINT_ERR = 120, 3.0, 15.0  # line snap as camera.py accepts it; point err: see judge()

_LN, _LF, _M = WIDTH / 2 - LANE_WIDTH / 2, WIDTH / 2 + LANE_WIDTH / 2, LENGTH / 2
LANDMARKS = {
    "L_corner_near": ((0, 0), "left baseline x near sideline"),
    "L_corner_far": ((0, WIDTH), "left baseline x far sideline"),
    "L_lane_base_near": ((0, _LN), "left lane line x baseline (near side)"),
    "L_lane_base_far": ((0, _LF), "left lane line x baseline (far side)"),
    "L_ft_near": ((FT_LINE, _LN), "left free-throw line, near end"),
    "L_ft_far": ((FT_LINE, _LF), "left free-throw line, far end"),
    "mid_near": ((_M, 0), "halfway line x near sideline"),
    "mid_far": ((_M, WIDTH), "halfway line x far sideline"),
    "circle_near": ((_M, WIDTH / 2 - CENTER_CIRCLE_R), "centre circle x halfway line (near)"),
    "circle_far": ((_M, WIDTH / 2 + CENTER_CIRCLE_R), "centre circle x halfway line (far)"),
    "R_ft_far": ((LENGTH - FT_LINE, _LF), "right free-throw line, far end"),
    "R_ft_near": ((LENGTH - FT_LINE, _LN), "right free-throw line, near end"),
    "R_lane_base_far": ((LENGTH, _LF), "right lane line x baseline (far side)"),
    "R_lane_base_near": ((LENGTH, _LN), "right lane line x baseline (near side)"),
    "R_corner_far": ((LENGTH, WIDTH), "right baseline x far sideline"),
    "R_corner_near": ((LENGTH, 0), "right baseline x near sideline"),
    "L_3pt_base_near": ((0, THREE_PT_SIDE), "left baseline x three-point line (near side)"),
    "L_3pt_base_far": ((0, WIDTH - THREE_PT_SIDE), "left baseline x three-point line (far side)"),
    "R_3pt_base_far": ((LENGTH, WIDTH - THREE_PT_SIDE), "right baseline x three-point line (far side)"),
    "R_3pt_base_near": ((LENGTH, THREE_PT_SIDE), "right baseline x three-point line (near side)"),
    "L_ft_circle_top": ((FT_LINE + CENTER_CIRCLE_R, WIDTH / 2), "left free-throw circle, point furthest from the baseline"),
    "R_ft_circle_top": ((LENGTH - FT_LINE - CENTER_CIRCLE_R, WIDTH / 2), "right free-throw circle, point furthest from the baseline"),
    "circle_left": ((_M - CENTER_CIRCLE_R, WIDTH / 2), "centre circle, leftmost point"),
    "circle_right": ((_M + CENTER_CIRCLE_R, WIDTH / 2), "centre circle, rightmost point"),
}


def court_xy(p: dict) -> tuple[float, float]:
    return tuple(p["court"]) if "court" in p else LANDMARKS[p["name"]][0]


def _label(p: dict) -> str:
    return p.get("name") or "court({:g},{:g})".format(*p["court"])


def fit(img, points: list[dict], iters=3, ignore_mask=None):
    """Points -> (H court->image refined on painted lines, median residual px, support)."""
    if len(points) < 4:
        raise ValueError("need >= 4 points")
    court = np.float32([court_xy(p) for p in points])
    pix = np.float32([p["px"] for p in points])
    H0, _ = cv2.findHomography(court, pix)
    if H0 is None:
        raise ValueError("degenerate points (collinear?)")
    return refine_homography(img, H0, ignore_mask=ignore_mask, iters=iters)


def point_errors(H, points: list[dict]) -> list[dict]:
    """Reprojection error of each point under H (worst first), plus the leave-one-out error
    (distance from the homography of the other points) when >= 5 points."""
    court = np.float32([court_xy(p) for p in points])
    pix = np.float32([p["px"] for p in points])
    err = np.linalg.norm(project(H, court) - pix, axis=1)
    out = []
    for k, p in enumerate(points):
        loo = None
        if len(points) >= 5:
            m = np.arange(len(points)) != k
            Hk, _ = cv2.findHomography(court[m], pix[m])
            loo = float(np.linalg.norm(project(Hk, court[k:k + 1])[0] - pix[k])) if Hk is not None else None
        out.append(dict(label=_label(p), err=float(err[k]), loo=loo))
    return sorted(out, key=lambda e: -e["err"])


def judge(med, sup, errs, max_point_err=PASS_POINT_ERR) -> bool:
    """Line snap accepted the way the tracker accepts it (support >= 120, median < 3 px), and every given
    point within max_point_err of the snapped court: eyeballed points are good to ~5-8 px, a larger miss
    means a mislabelled point or a snap onto the wrong line (refine searches 25 px)."""
    return sup >= PASS_SUPPORT and med < PASS_MEDIAN and all(e["err"] <= max_point_err for e in errs)


def report_line(t, points, H, med, sup, max_point_err=PASS_POINT_ERR):
    """-> (passed, `PASS|WEAK t=..` line, worst-points line)."""
    errs = point_errors(H, points)
    ok = judge(med, sup, errs, max_point_err)
    rms = float(np.sqrt(np.mean([e["err"] ** 2 for e in errs])))
    line = f"{'PASS' if ok else 'WEAK'} t={t:g} points={len(points)} rms={rms:.1f} support={sup} median={med:.2f}"
    worst = "  worst: " + ", ".join(
        f"{e['label']}={e['err']:.1f}px" + (f" (loo {e['loo']:.1f})" if e["loo"] is not None else "") for e in errs[:3])
    return ok, line, worst


def _minimap(target=None, scale=9, pad=6, numbered=False):
    w, h = int(LENGTH * scale) + 2 * pad, int(WIDTH * scale) + 2 * pad
    m = np.full((h, w, 3), 40, np.uint8)

    def px(x, y):
        return int(pad + x * scale), int(pad + (WIDTH - y) * scale)  # near sideline at the bottom
    for pl in court_polylines():
        cv2.polylines(m, [np.int32([px(x, y) for x, y in pl])], False, (230, 230, 230), 1)
    if target is not None:
        cv2.circle(m, px(*target), 5, (0, 0, 255), -1)
    if numbered:
        for k, (xy, _) in enumerate(LANDMARKS.values()):
            q = px(*xy)
            cv2.circle(m, q, 3, (0, 0, 255), -1)
            dx = 5 if xy[0] < LENGTH / 2 else -5 - 8 * len(str(k))
            dy = -4 if xy[1] > WIDTH / 2 else 13
            cv2.putText(m, str(k), (q[0] + dx, q[1] + dy), 0, 0.4, (0, 255, 255), 1, cv2.LINE_AA)
    return m


def landmark_table() -> str:
    return "\n".join(f"{k:2d} {n:17s} ({xy[0]:5.2f}, {xy[1]:5.2f})  {d}"
                     for k, (n, (xy, d)) in enumerate(LANDMARKS.items()))


def grid_image(img, minor=50, major=100):
    """Frame with a labelled pixel grid (every 50 px, labels every 100); the numbered landmark map and
    legend are appended below, so frame pixel coordinates are unchanged."""
    h, w = img.shape[:2]
    lines = img.copy()
    for x in range(0, w, minor):
        cv2.line(lines, (x, 0), (x, h), (0, 255, 255) if x % major == 0 else (0, 140, 255), 1)
    for y in range(0, h, minor):
        cv2.line(lines, (0, y), (w, y), (0, 255, 255) if y % major == 0 else (0, 140, 255), 1)
    vis = cv2.addWeighted(img, 0.45, lines, 0.55, 0)
    fs = 0.4

    def tag(text, x, y):  # (x, y) = baseline-left of the text
        (tw, th), _ = cv2.getTextSize(text, 0, fs, 1)
        cv2.rectangle(vis, (x - 1, y - th - 2), (x + tw + 1, y + 2), (0, 0, 0), -1)
        cv2.putText(vis, text, (x, y), 0, fs, (0, 255, 255), 1, cv2.LINE_AA)
    for x in range(major, w, major):  # plain numbers on the edges (x top/bottom, y left/right)
        tag(str(x), x + 2, 12)
        tag(str(x), x + 2, h - 4)
    for y in range(major, h, major):
        tag(str(y), 2, y - 3)
        tag(str(y), w - 30, y - 3)
    for x in range(2 * major, w - 90, 2 * major):  # "x,y" at every other major crossing inside the frame
        for y in range(2 * major, h - 30, 2 * major):
            tag(f"{x},{y}", x + 2, y - 3)
    mm = _minimap(numbered=True, scale=max(9, min(16, int(w * 0.4 / LENGTH))))
    names = list(LANDMARKS)
    rows = max(1, (mm.shape[0] - 24) // 15)
    col_w, x0 = 150, mm.shape[1] + 16
    panel = np.zeros((mm.shape[0] + 8, max(w, x0 + col_w * -(-len(names) // rows)), 3), np.uint8)
    panel[4:4 + mm.shape[0], 4:4 + mm.shape[1]] = mm
    for k, n in enumerate(names):
        cv2.putText(panel, f"{k} {n}", (x0 + (k // rows) * col_w, 16 + (k % rows) * 15), 0, 0.4,
                    (230, 230, 230), 1, cv2.LINE_AA)
    cv2.putText(panel, "map: left baseline x=0 on the left, near (camera) sideline y=0 at the bottom",
                (x0, panel.shape[0] - 8), 0, 0.4, (150, 150, 150), 1, cv2.LINE_AA)
    if panel.shape[1] > w:
        vis = np.hstack([vis, np.zeros((h, panel.shape[1] - w, 3), np.uint8)])
    return np.vstack([vis, panel])


def points_overlay(img, H, points):
    """Court overlay + each given point (green) linked to where H puts its landmark (red)."""
    vis = draw_court_overlay(img, H)
    for p in points:
        q = tuple(int(round(v)) for v in p["px"])
        r = tuple(int(round(v)) for v in project(H, np.float32([court_xy(p)]))[0])
        cv2.line(vis, q, r, (0, 0, 255), 1)
        cv2.circle(vis, r, 4, (0, 0, 255), -1)
        cv2.circle(vis, q, 4, (0, 255, 0), -1)
        cv2.putText(vis, _label(p), (q[0] + 6, q[1] - 6), 0, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    return vis


def pick_points(img, title="calibrate") -> list[dict]:
    """OpenCV window: click each highlighted landmark; s=skip, u=undo, Enter=done (>= 4), Esc=abort."""
    names, picked, clicks, i = list(LANDMARKS), {}, [], 0
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(title, lambda ev, x, y, *_: clicks.append((x, y)) if ev == cv2.EVENT_LBUTTONDOWN else None)
    while True:
        vis = img.copy()
        for n, (x, y) in picked.items():
            cv2.circle(vis, (x, y), 5, (0, 0, 255), -1)
            cv2.putText(vis, n, (x + 6, y - 6), 0, 0.5, (0, 255, 255), 1)
        msg = (f"Click: {LANDMARKS[names[i]][1]}  (red dot on map)" if i < len(names) else "All landmarks offered")
        lines = [msg, f"[s] skip (not visible)  [u] undo  [Enter] done ({len(picked)} picked, need >= 4)  [Esc] abort"]
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 52), (0, 0, 0), -1)
        for k, t in enumerate(lines):
            cv2.putText(vis, t, (8, 20 + 24 * k), 0, 0.6, (255, 255, 255), 1)
        if i < len(names):
            mm = _minimap(LANDMARKS[names[i]][0])
            vis[56:56 + mm.shape[0], vis.shape[1] - mm.shape[1] - 4:vis.shape[1] - 4] = mm
        cv2.imshow(title, vis)
        key = cv2.waitKey(30) & 0xFF
        if clicks and i < len(names):
            picked[names[i]] = clicks.pop()
            i += 1
        elif key == ord("s") and i < len(names):
            i += 1
        elif key == ord("u") and i > 0:
            i -= 1
            picked.pop(names[i], None)
        elif key in (10, 13) and len(picked) >= 4:
            break
        elif key == 27:
            cv2.destroyWindow(title)
            raise SystemExit("aborted")
        if i >= len(names):
            clicks.clear()
    cv2.destroyWindow(title)
    return [{"name": n, "px": [int(x), int(y)]} for n, (x, y) in picked.items()]


def grab(cap, t: float, required=True):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * cap.get(cv2.CAP_PROP_FPS))))
    ok, f = cap.read()
    if not ok:
        if required:
            raise SystemExit(f"cannot read frame at {t} s")
        return None
    return f


def _frames(cap, f0, f1, step, extra=(), chunk=40):
    """Yield (frame index, bgr) every `step` frames from f0 to f1 inclusive, plus the `extra` frames in
    range; backward when f1 < f0 (decodes short forward runs and replays them reversed)."""
    s = 1 if f1 >= f0 else -1
    want = sorted(set(range(f0, f1 + s, s * step)) | {f for f in extra if min(f0, f1) <= f <= max(f0, f1)},
                  reverse=s < 0)
    parts = [want] if s > 0 else [want[k:k + chunk] for k in range(0, len(want), chunk)]
    for part in parts:
        lo, hi, wanted, buf = min(part), max(part), set(part), []
        cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
        for fi in range(lo, hi + 1):
            if fi in wanted:
                ok, fr = cap.read()
                if not ok:
                    break
                if s > 0:
                    yield fi, fr
                else:
                    buf.append((fi, fr))
            elif not cap.grab():
                break
        else:
            yield from reversed(buf)
            continue
        yield from reversed(buf)
        return


def propagate(cap, keyframes: list[dict], targets: list[float], start: float, step=6, max_q=3.0, boxes=None):
    """Track the camera from `start` to the targets (backward for targets before it, forward for the rest);
    return {t: (frame, H, q)} for targets reached with a refined fit (q = median px < max_q).
    `boxes` = {frame index: person boxes} masks players out of the flow, SIFT and line snapping."""
    bank = KeyframeBank()
    for kf in keyframes:
        bank.add(cv2.cvtColor(kf["img"], cv2.COLOR_BGR2GRAY), np.array(kf["H"]))
    fps = cap.get(cv2.CAP_PROP_FPS)
    f0, got, boxes = int(round(start * fps)), {}, boxes or {}
    for back, todo in ((True, sorted((t for t in targets if t < start), reverse=True)),
                       (False, sorted(t for t in targets if t >= start))):
        if not todo:
            continue
        fr_of = {t: int(round(t * fps)) for t in todo}
        trk = CourtCameraTracker(bank)  # the first update localises the start frame against the bank
        for fi, fr in _frames(cap, f0, fr_of[todo[-1]], step, fr_of.values()):
            H, q, how = trk.update(fr, boxes.get(fi, []))
            while todo and (fi <= fr_of[todo[0]] if back else fi >= fr_of[todo[0]]):
                t = todo.pop(0)
                good = H is not None and q < max_q
                print(f"  t={t:g} q={q:.2f} via {how}" + ("" if good else "  -> skipped"))
                if good:
                    got[t] = (fr, H.copy(), q)
            if not todo:
                break
        for t in todo:
            print(f"  t={t:g} not reached (end of video?)  -> skipped")
    return got


def load_boxes(path, min_conf=0.45) -> dict:
    """detections.pkl of the same video (extract pass 1) -> {frame index: person boxes}."""
    import pandas as pd
    det = pd.read_pickle(path)
    p = det[(det.kind == "person") & (det.conf > min_conf)]
    return {int(f): g[["x1", "y1", "x2", "y2"]].to_numpy() for f, g in p.groupby("frame")}


def load_keyframes(path) -> list[dict]:
    """keyframes.json -> [{img, H, ...}], image paths resolved relative to the file."""
    path = Path(path)
    out = []
    for kf in json.loads(path.read_text(encoding="utf-8")):
        img = cv2.imread(str(path.parent / kf["image"]))  # absolute paths survive the join
        if img is None:
            raise FileNotFoundError(path.parent / kf["image"])
        out.append({**kf, "img": img})
    return out


def load_bank(path) -> KeyframeBank:
    bank = KeyframeBank()
    for kf in load_keyframes(path):
        bank.add(cv2.cvtColor(kf["img"], cv2.COLOR_BGR2GRAY), np.array(kf["H"]))
    return bank


def _times(s: str) -> list[float]:
    return [float(x) for x in s.split(",") if x.strip()]


def write_grids(cap, times, out: Path):
    print("landmarks (court metres: x from the left baseline, y from the near sideline):")
    print(landmark_table())
    for t in times:
        img = grab(cap, t, required=False)
        if img is None:
            print(f"WARNING: cannot read frame at {t:g} s")
            continue
        path = out / f"grid_{t:g}.jpg"
        cv2.imwrite(str(path), grid_image(img), [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"grid t={t:g} -> {path}  ({img.shape[1]}x{img.shape[0]})")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner calibrate", description=__doc__.splitlines()[0])
    ap.add_argument("--video", required=True)
    ap.add_argument("--times", required=True, help="comma-separated seconds of frames to calibrate from points")
    ap.add_argument("--out", required=True, help="directory for keyframes.json + images")
    ap.add_argument("--grid", action="store_true", help="only write grid_<t>.jpg (pixel grid + landmark map), no GUI")
    ap.add_argument("--points", help="points.json (non-interactive)")
    ap.add_argument("--propagate", default="", help="comma-separated seconds: extra keyframes by camera tracking")
    ap.add_argument("--step", type=int, default=6, help="track every Nth video frame when propagating")
    ap.add_argument("--detections", help="detections.pkl of this video: mask player boxes")
    ap.add_argument("--max-point-err", type=float, default=PASS_POINT_ERR,
                    help="px: a given point further than this from the snapped court makes the frame WEAK")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {a.video}")
    times = _times(a.times)
    if a.grid:
        write_grids(cap, times, out)
        return 0
    given = json.loads(Path(a.points).read_text(encoding="utf-8")) if a.points else {}
    picked = {f"{float(k):g}": v for k, v in given.items()}
    boxes = load_boxes(a.detections) if a.detections else {}
    fps = cap.get(cv2.CAP_PROP_FPS)
    kfs, all_ok = [], True
    for t in times:
        key = f"{t:g}"
        img = grab(cap, t, required=not a.points)
        if img is None:
            print(f"WEAK t={key} cannot read the frame")
            all_ok = False
            continue
        if key not in picked:
            if a.points:
                print(f"WARNING: no points for t={key} in {a.points}; skipped")
                all_ok = False
                continue
            picked[key] = pick_points(img, f"calibrate t={key}s")
            (out / "points.json").write_text(json.dumps(picked, indent=1), encoding="utf-8")
        pm = _people_mask(img.shape, boxes.get(int(round(t * fps)), [])) if boxes else None
        try:
            H, med, sup = fit(img, picked[key], ignore_mask=pm)
        except (ValueError, KeyError) as e:
            print(f"WEAK t={key} bad points: {e!r}")
            all_ok = False
            continue
        ok, line, worst = report_line(t, picked[key], H, med, sup, a.max_point_err)
        print(line)
        print(worst)
        cv2.imwrite(str(out / f"ov_{key}.jpg"), points_overlay(img, H, picked[key]))
        all_ok &= ok
        if ok or not a.points:  # the interactive picker keeps every frame, as before
            kfs.append(dict(t=t, img=img, H=H, median_px=round(med, 2), support=sup, source="points"))
    if a.propagate:
        targets = _times(a.propagate)
        if kfs:
            start = min(k["t"] for k in kfs)
            print(f"propagating from {start:g}")
            got = propagate(cap, kfs, targets, start, a.step, boxes=boxes)
        else:
            print("WARNING: no passing keyframe to propagate from")
            got = {}
        for t in targets:
            if t in got:
                fr, H, q = got[t]
                print(f"PASS t={t:g} propagated median={q:.2f}")
                kfs.append(dict(t=t, img=fr, H=H, median_px=round(q, 2), source="propagated"))
                cv2.imwrite(str(out / f"ov_{t:g}.jpg"), draw_court_overlay(fr, H))
            else:
                print(f"WEAK t={t:g} propagation did not reach a refined fit")
                all_ok = False
    entries = []
    for kf in kfs:
        name = f"kf_{kf['t']:g}.png"
        cv2.imwrite(str(out / name), kf["img"])
        entries.append({"image": name, "H": np.asarray(kf["H"]).tolist(),
                        **{k: v for k, v in kf.items() if k not in ("img", "H")}})
    (out / "keyframes.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    print(len(entries), "keyframes ->", out / "keyframes.json")
    if not all_ok:  # exit code 2 (cli.py ignores return values), after everything that passed is written
        print("some frames are WEAK or missing: fix their points (see ov_<t>.jpg) and re-run", flush=True)
        raise SystemExit(2)
    return 0


if __name__ == "__main__":
    main()
