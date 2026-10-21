"""CLI: how good are the player tracks? Label-free proxy metrics from a run, and HOTA / IDF1 against labelled clips.

Reads RUN/tracks.pkl (or --tracks), RUN/jersey.json, RUN/camera.npz and, with --stitch, RUN/stitch.json (tracklets
joined into chains). With --gt (a MOT 1.1 `gt.txt` from CVAT for a short clip of our video) it also scores the
tracks with TrackEval (HOTA, DetA, AssA, IDF1, MOTA, ID switches) on the frames both have. Writes --out JSON.

Proxy metrics need no labels: tracklet length, the share of player-time with a jersey number, tracks whose
jersey reads show two numbers (an identity switch inside the track), frames where two tracks claim the same
(team, number) and frames with more than five tracks of one team. They move with tracking quality but are not
ground truth: a merge of two unread tracklets is invisible to them.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

MOT_COLS = ["frame", "id", "x", "y", "w", "h"]
TEAMS = ("us", "them")


def read_mot(path: str | Path) -> pd.DataFrame:
    """MOT 1.1 / MOTChallenge txt (frame, id, x, y, w, h[, considered, class, visibility]) -> DataFrame.
    Rows marked not considered (7th column 0, CVAT's "ignored") are dropped."""
    df = pd.read_csv(path, header=None)
    df = df.rename(columns=dict(enumerate(MOT_COLS + ["considered", "cls", "vis"])))
    if "considered" in df:
        df = df[df.considered != 0]
    df[["frame", "id"]] = df[["frame", "id"]].astype(int)
    return df.reset_index(drop=True)


def tracks_to_mot(tr: pd.DataFrame, frame0: int = 0, frame1: int | None = None, id_col: str = "track") -> pd.DataFrame:
    """tracks.pkl rows with frame0 <= frame < frame1 -> MOT rows (video frame numbers, ids from 1)."""
    m = tr.frame >= frame0
    if frame1 is not None:
        m &= tr.frame < frame1
    s = tr[m]
    ids = {t: i + 1 for i, t in enumerate(sorted(s[id_col].unique()))}
    return pd.DataFrame(dict(frame=s.frame.astype(int).to_numpy(), id=s[id_col].map(ids).to_numpy(),
                             x=s.x1.to_numpy(), y=s.y1.to_numpy(), w=(s.x2 - s.x1).to_numpy(),
                             h=(s.y2 - s.y1).to_numpy())).sort_values(["frame", "id"]).reset_index(drop=True)


def write_mot(mot: pd.DataFrame, path: str | Path, frame0: int = 0, step: int = 1):
    """MOT 1.1 txt for CVAT import: video frame frame0 + k * step becomes clip frame k + 1 (a clip cut at the
    sampled rate), considered=1, class 1, visibility 1."""
    mot = mot[(mot.frame - frame0) % step == 0]
    out = mot.assign(frame=(mot.frame - frame0) // step + 1, considered=1, cls=1, vis=1.0)
    out[MOT_COLS + ["considered", "cls", "vis"]].to_csv(path, header=False, index=False, float_format="%.1f")


def gt_to_video_frames(gt: pd.DataFrame, start_s: float, gt_fps: float, video_fps: float) -> pd.DataFrame:
    """Clip frame k (1-based) of a clip cut at start_s and played at gt_fps -> frame number of our video."""
    f0 = round(start_s * video_fps)
    return gt.assign(frame=f0 + np.rint((gt.frame - 1) * video_fps / gt_fps).astype(int))


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between xywh boxes a (n x 4) and b (m x 4)."""
    ax2, ay2 = a[:, 0] + a[:, 2], a[:, 1] + a[:, 3]
    bx2, by2 = b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    iw = np.clip(np.minimum(ax2[:, None], bx2[None]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    ih = np.clip(np.minimum(ay2[:, None], by2[None]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    inter = iw * ih
    union = (a[:, 2] * a[:, 3])[:, None] + (b[:, 2] * b[:, 3])[None] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def score_mot(gt: pd.DataFrame, pred: pd.DataFrame, frames: set | None = None) -> dict:
    """TrackEval HOTA / CLEAR / Identity of pred against gt (MOT DataFrames, same frame numbering), on `frames`
    (default: every frame of gt). Needs the optional `trackeval` package (dev dependency)."""
    from trackeval.metrics import CLEAR, HOTA, Identity

    frames = sorted(frames if frames is not None else set(gt.frame))
    gt = gt[gt.frame.isin(frames)]
    pred = pred[pred.frame.isin(frames)]
    gid = {v: i for i, v in enumerate(sorted(gt.id.unique()))}
    pid = {v: i for i, v in enumerate(sorted(pred.id.unique()))}
    g_by, p_by = dict(tuple(gt.groupby("frame"))), dict(tuple(pred.groupby("frame")))
    empty = gt.iloc[:0]
    data = dict(num_timesteps=len(frames), num_gt_ids=len(gid), num_tracker_ids=len(pid),
                num_gt_dets=len(gt), num_tracker_dets=len(pred), gt_ids=[], tracker_ids=[], similarity_scores=[])
    for f in frames:
        g, p = g_by.get(f, empty), p_by.get(f, empty)
        data["gt_ids"].append(g.id.map(gid).to_numpy(int))
        data["tracker_ids"].append(p.id.map(pid).to_numpy(int))
        data["similarity_scores"].append(_iou(g[["x", "y", "w", "h"]].to_numpy(float),
                                              p[["x", "y", "w", "h"]].to_numpy(float)))
    quiet = {"PRINT_CONFIG": False}
    h = HOTA(quiet).eval_sequence(data)
    c = CLEAR(quiet).eval_sequence(data)
    i = Identity(quiet).eval_sequence(data)
    return dict(HOTA=float(np.mean(h["HOTA"])), DetA=float(np.mean(h["DetA"])), AssA=float(np.mean(h["AssA"])),
                IDF1=float(i["IDF1"]), MOTA=float(c["MOTA"]), IDSW=int(c["IDSW"]), frames=len(frames),
                gt_ids=len(gid), pred_ids=len(pid))


def strong_numbers(reads: list[str], min_reads: int = 2) -> list[str]:
    """Numbers read at least min_reads times in one track ("none" ignored)."""
    c = Counter(r for r in reads if r != "none")
    return [n for n, k in c.items() if k >= min_reads]


def proxy_metrics(tr: pd.DataFrame, numbers: dict, reads: dict, fps: float, id_col: str = "track") -> dict:
    """Label-free tracking quality of us/them tracks.

    numbers: track -> jersey number (identities); reads: track -> jersey reads ("none" included).
    """
    p = tr[tr.team.isin(TEAMS)]
    n = p.groupby(id_col).size()
    sec = n / fps
    has_num = p[id_col].map(lambda t: t in numbers and str(numbers[t]) != "none")
    mixed = {t: strong_numbers(r) for t, r in reads.items() if t in n.index}
    mixed = {t: k for t, k in mixed.items() if len(k) >= 2}
    per = p.assign(number=p[id_col].map(lambda t: numbers.get(t)))
    frames = p.frame.nunique()
    numd = per[per.number.notna() & (per.number.astype(str) != "none")]
    clash = numd.groupby(["frame", "team", "number"])[id_col].nunique()
    clash_frames = clash[clash > 1].index.get_level_values("frame").nunique()
    count = p.groupby(["frame", "team"])[id_col].nunique()
    over = count[count > 5].index.get_level_values("frame").nunique()
    return dict(tracklets=int(len(n)), median_len_s=float(sec.median()) if len(n) else 0.0,
                p90_len_s=float(sec.quantile(0.9)) if len(n) else 0.0,
                time_in_10s_tracks=float(n[sec >= 10].sum() / max(n.sum(), 1)),
                id_coverage=float(has_num.mean()) if len(p) else 0.0,
                mixed_tracks=len(mixed), implied_switches=int(sum(len(k) - 1 for k in mixed.values())),
                number_conflict_frames=float(clash_frames / max(frames, 1)),
                over5_frames=float(over / max(frames, 1)), player_rows=int(len(p)))


def _numbers_and_reads(tr: pd.DataFrame, jersey: dict) -> tuple[dict, dict]:
    reads = {int(k): [str(r) for r in v.get("reads", [])] for k, v in jersey.items()}
    if "number" in tr:
        s = tr.dropna(subset=["number"]).groupby("track").number.first()
        numbers = {int(k): str(v) for k, v in s.items()}
    else:
        numbers = {int(k): str(v["number"]) for k, v in jersey.items() if str(v["number"]) != "none"}
    return numbers, reads


def main(argv=None):
    from .camera import sampled_fps
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--tracks", default=None, help="tracks pickle (default RUN/tracks.pkl)")
    ap.add_argument("--jersey", default=None, help="jersey reads (default RUN/jersey.json)")
    ap.add_argument("--stitch", default=None, help="stitch.json: score chains instead of tracklets")
    ap.add_argument("--gt", default=None, help="MOT 1.1 gt.txt of a labelled clip (CVAT export)")
    ap.add_argument("--gt-start", type=float, default=0.0, help="second of our video where the clip starts")
    ap.add_argument("--gt-fps", type=float, default=None, help="frame rate of the labelled clip (default: sampled fps)")
    ap.add_argument("--export-mot", default=None, help="write our tracks for the --gt-start/--gt-len window as MOT "
                    "txt (pre-labels to correct in CVAT)")
    ap.add_argument("--gt-len", type=float, default=120.0, help="clip length in seconds for --export-mot")
    ap.add_argument("--out", default=None, help="JSON output (default: print)")
    args = ap.parse_args(argv)
    run = Path(args.run)
    tr = pd.read_pickle(args.tracks or run / "tracks.pkl")
    jp = Path(args.jersey) if args.jersey else run / "jersey.json"
    jersey = json.loads(jp.read_text()) if jp.exists() else {}
    fps = sampled_fps(run)
    cam = np.load(run / "camera.npz")
    vfps = float(np.median(np.diff(cam["frame"])) * fps) if len(cam["frame"]) > 1 else fps
    if args.stitch:
        from .stitch import apply_stitch
        st = json.loads(Path(args.stitch).read_text())
        tr = apply_stitch(tr, st)
        numbers = {int(k): v["number"] for k, v in st["chains"].items() if v.get("number", "none") != "none"}
        reads = {int(k): v.get("reads", []) for k, v in st["chains"].items()}
    else:
        numbers, reads = _numbers_and_reads(tr, jersey)
    out = {"proxy": proxy_metrics(tr, numbers, reads, fps)}
    f0 = round(args.gt_start * vfps)
    if args.export_mot:
        cf = cam["frame"].astype(int)
        f0 = int(cf[np.argmin(abs(cf - f0))]) if len(cf) else f0      # a frame extract kept
        step = max(int(round(vfps / fps)), 1)
        write_mot(tracks_to_mot(tr, f0, f0 + round(args.gt_len * vfps)), args.export_mot, frame0=f0, step=step)
        print(f"wrote {args.export_mot}: clip frame 1 = video frame {f0}; cut the clip at {f0 / vfps:.3f} s with "
              f"fps={fps:g} and score it with --gt-start {f0 / vfps:.3f} --gt-fps {fps:g}")
    if args.gt:
        gt = gt_to_video_frames(read_mot(args.gt), args.gt_start, args.gt_fps or fps, vfps)
        pred = tracks_to_mot(tr[tr.team.isin(TEAMS + ("ref",))], gt.frame.min(), gt.frame.max() + 1)
        out["gt"] = score_mot(gt, pred, frames=set(gt.frame) & set(cam["frame"].astype(int)))
    txt = json.dumps(out, indent=1)
    if args.out:
        Path(args.out).write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
