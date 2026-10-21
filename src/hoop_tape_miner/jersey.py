"""Pass 3: jersey number recognition per tracklet with a local VLM (Qwen3-VL, 4-bit)."""
from __future__ import annotations

import re
from collections import Counter

import cv2
import numpy as np
import pandas as pd
import torch

from .device import device

VLM_ID = "Qwen/Qwen3-VL-4B-Instruct"
PROMPT = ("What number is printed on this basketball player's jersey? "
          "Reply with only the number (e.g. 17). If no number is clearly legible reply: none")


def pick_crops(tr: pd.DataFrame, all_df: pd.DataFrame, k=4) -> pd.DataFrame:
    """Pick k large, well-separated, unoccluded detections spread over the tracklet."""
    tr = tr.assign(h=tr.y2 - tr.y1).query("h > 60")
    if tr.empty:
        return tr
    # occlusion: another person box overlapping this one in the same frame
    by_frame = {f: g for f, g in all_df[all_df.frame.isin(tr.frame)].groupby("frame")}  # group once, not per row
    clean = []
    for idx, r in tr.iterrows():
        o = by_frame.get(r.frame, all_df.iloc[:0])
        o = o[o.index != idx]
        ix = np.clip(np.minimum(o.x2, r.x2) - np.maximum(o.x1, r.x1), 0, None)
        iy = np.clip(np.minimum(o.y2, r.y2) - np.maximum(o.y1, r.y1), 0, None)
        frac = (ix * iy).max() / ((r.x2 - r.x1) * (r.y2 - r.y1)) if len(o) else 0
        clean.append(frac < 0.15)
    tr = tr[np.array(clean)]
    if tr.empty:
        return tr
    tr = tr.sort_values("frame")
    parts = np.array_split(np.arange(len(tr)), min(k, len(tr)))
    return pd.DataFrame([tr.iloc[ix].sort_values("h").iloc[-1] for ix in parts if len(ix)])


def upper_body(img: np.ndarray, r, height=256) -> np.ndarray | None:
    """Jersey region (top ~60% of the box), upscaled so digits are ~40px tall."""
    x1, y1, x2, y2 = int(r.x1), int(r.y1), int(r.x2), int(r.y2)
    pad = int(0.1 * (x2 - x1))
    c = img[max(y1, 0):int(y1 + 0.6 * (y2 - y1)), max(x1 - pad, 0):x2 + pad]
    if c.size == 0:
        return None
    s = height / c.shape[0]
    return cv2.resize(c, (int(c.shape[1] * s), height), interpolation=cv2.INTER_CUBIC)


SHOULDERS, HIPS = (5, 6), (11, 12)                     # COCO keypoint ids


def person_crop(img: np.ndarray, r, pad: float = 0.1) -> tuple[np.ndarray, int, int] | None:
    """Whole detection box with a margin -> (crop, x offset, y offset) for the pose model."""
    w, h = r.x2 - r.x1, r.y2 - r.y1
    x1, y1 = max(int(r.x1 - pad * w), 0), max(int(r.y1 - pad * h), 0)
    c = img[y1:int(r.y2 + pad * h), x1:int(r.x2 + pad * w)]
    return (c, x1, y1) if c.size else None


def torso_box(K: np.ndarray, C: np.ndarray, min_conf: float = 0.4, min_ratio: float = 0.3,
              margin: float = 0.15) -> tuple[int, int, int, int] | None:
    """One person's 17 COCO keypoints (K: xy, C: confidence) -> the torso rectangle (shoulders to hips plus a
    margin) when the number can be legible: both shoulders and both hips seen and the shoulders at least
    min_ratio of the torso height apart (a side-on torso hides the number). None otherwise."""
    idx = list(SHOULDERS + HIPS)
    if (C[idx] < min_conf).any():
        return None
    sh, hp = K[list(SHOULDERS)], K[list(HIPS)]
    height = hp[:, 1].mean() - sh[:, 1].mean()
    width = abs(sh[0, 0] - sh[1, 0])
    if height <= 0 or width < min_ratio * height:
        return None
    xs, ys = K[idx, 0], K[idx, 1]
    mx, my = margin * height, margin * height
    return int(xs.min() - mx), int(ys.min() - my), int(xs.max() + mx), int(ys.max() + my)


def pick_pose(boxes: np.ndarray, shape: tuple[int, int]) -> int:
    """Index of the pose detection that is the cropped player: the box whose centre is nearest the crop centre."""
    if not len(boxes):
        return -1
    cx, cy = (boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2
    return int(np.argmin(np.hypot(cx - shape[1] / 2, cy - shape[0] / 2)))


def resize_h(c: np.ndarray, height: int = 256) -> np.ndarray:
    s = height / c.shape[0]
    return cv2.resize(c, (max(int(c.shape[1] * s), 1), height), interpolation=cv2.INTER_CUBIC)


def tracklet_record(crops: list[dict], min_weight: float = 1.5) -> dict:
    """Per-crop reads [{idx, frame, read, conf, legible}] -> the jersey.json entry of one tracklet: confidence-
    weighted vote, the reads in time order and the crop records (stitch pools them per player chain)."""
    crops = sorted(crops, key=lambda c: c["frame"])
    num = weighted_vote([(c["read"], c["conf"]) for c in crops], min_weight=min_weight)[0]
    return dict(number=num, reads=[c["read"] for c in crops], crops=crops)


class PoseGate:
    """Batched YOLO pose over person crops: each slot (a [idx, frame, crop] list) gets its torso crop (resized for
    the reader) when the torso is legible, else stays None."""

    def __init__(self, batch: int = 32):
        from .train_scan import POSE_MODEL, model
        self.model, self.batch, self.todo, self.legible = model(POSE_MODEL), batch, [], 0

    def add(self, pc, slot: list):
        self.todo.append((pc, slot))
        if len(self.todo) >= self.batch:
            self.flush()

    def flush(self):
        if not self.todo:
            return
        res = self.model([pc[0] for pc, _ in self.todo], verbose=False)
        for (pc, slot), r in zip(self.todo, res):
            img = pc[0]
            if r.keypoints is None or not len(r.boxes):
                continue
            k = pick_pose(r.boxes.xyxy.cpu().numpy(), img.shape[:2])
            K = r.keypoints.xy.cpu().numpy()[k]
            C = r.keypoints.conf.cpu().numpy()[k] if r.keypoints.conf is not None else np.ones(len(K))
            box = torso_box(K, C)
            if box is None:
                continue
            x1, y1, x2, y2 = box
            c = img[max(y1, 0):max(y2, 0), max(x1, 0):max(x2, 0)]
            if c.size and c.shape[0] >= 8:
                slot[2] = resize_h(c)
                self.legible += 1
        self.todo = []


class JerseyReader:
    def __init__(self):
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration
        self.processor = AutoProcessor.from_pretrained(VLM_ID)
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            VLM_ID, quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
                                                           bnb_4bit_quant_type="nf4"),
            device_map=device()).eval()  # 4-bit bitsandbytes still needs CUDA in practice

    @torch.no_grad()
    def read(self, bgr_grid: np.ndarray) -> tuple[str, float]:
        """Crop -> (number or "none", confidence): the probability the model gave its whole greedy answer."""
        from PIL import Image
        img = Image.fromarray(bgr_grid[:, :, ::-1])
        msgs = [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": PROMPT}]}]
        inputs = self.processor.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                                    return_dict=True, return_tensors="pt").to(device())
        out = self.model.generate(**inputs, max_new_tokens=8, do_sample=False, output_scores=True,
                                  return_dict_in_generate=True)
        seq = out.sequences[0, inputs["input_ids"].shape[1]:]
        special = set(self.processor.tokenizer.all_special_ids)
        logp = [torch.log_softmax(s[0].float(), -1)[t].item() for s, t in zip(out.scores, seq)
                if int(t) not in special]
        txt = self.processor.tokenizer.decode(seq, skip_special_tokens=True)
        m = re.search(r"\d{1,2}", txt)
        return (m.group(0) if m else "none"), float(np.exp(sum(logp)))


def vote(reads: list[str], min_agree=2) -> str:
    nums = [r for r in reads if r != "none"]
    if not nums:
        return "none"
    n, c = Counter(nums).most_common(1)[0]
    return n if c >= min_agree and c > len(nums) / 2 else "none"


def weighted_vote(reads, min_weight: float = 1.5, roster=None) -> tuple[str, float, float]:
    """reads: [(number, confidence)] ("none" ignored; reads off a non-empty roster ignored) ->
    (number, its weight, its share of the weight). The number wins with weight >= min_weight and more than half
    the weight; with confidence 1 per read this is the old rule (at least 2 agreeing reads, a strict majority)."""
    roster = {str(x) for x in roster or []}
    w = Counter()
    for n, c in reads:
        n = str(n)
        if n != "none" and (not roster or n in roster):
            w[n] += float(c)
    if not w:
        return "none", 0.0, 0.0
    n, top = w.most_common(1)[0]
    share = top / sum(w.values())
    return (n if top >= min_weight and share > 0.5 else "none"), top, share


def crop_table(jersey: dict) -> pd.DataFrame:
    """jersey.json -> one row per read crop: track, idx (detections.pkl row), frame, read, conf. Only for runs
    written with crop records (see legacy_crop_reads for older ones)."""
    rows = [dict(track=int(t), **c) for t, v in jersey.items() for c in v.get("crops", [])]
    return pd.DataFrame(rows, columns=["track", "idx", "frame", "read", "conf"])


def legacy_crop_reads(tr: pd.DataFrame, det: pd.DataFrame, jersey: dict, k: int = 6) -> pd.DataFrame:
    """Older jersey.json files keep only the reads per tracklet. The crop pick is deterministic, so picking again
    on the same tracks.pkl / detections.pkl gives the detection behind each read (tracklets whose pick count does
    not match their reads are skipped). Returns the crop_table columns, conf 1."""
    persons = det[det.kind == "person"]
    rows = []
    for tid, g in tr[tr.track.isin([int(t) for t in jersey])].groupby("track"):
        reads = jersey[str(tid)]["reads"]
        pk = pick_crops(g, persons[persons.frame.isin(g.frame)], k=k)
        if len(pk) != len(reads):
            continue
        rows += [dict(track=int(tid), idx=int(i), frame=int(f), read=str(r), conf=1.0)
                 for i, f, r in zip(pk.index, pk.frame, reads)]
    return pd.DataFrame(rows, columns=["track", "idx", "frame", "read", "conf"])


def main(argv=None):
    import argparse
    import json
    from pathlib import Path

    from .stitch import base_tracks

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--min-len", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tracks", default=None, help="tracks pickle (default RUN/tracks.pkl)")
    ap.add_argument("--out", default=None, help="output (default RUN/jersey.json; debug strips next to it)")
    ap.add_argument("--no-pose", action="store_true",
                    help="read the upper 60%% of every picked box (the old crop) instead of the pose torso crop "
                    "with its legibility gate")
    args = ap.parse_args(argv)
    run = Path(args.run)
    out_path = Path(args.out) if args.out else run / "jersey.json"
    tr = base_tracks(pd.read_pickle(args.tracks or run / "tracks.pkl"))   # tracklets, also after a stitch
    det = pd.read_pickle(run / "detections.pkl")
    persons = det[det.kind == "person"]
    lens = tr.groupby("track").size()
    cand = lens[lens >= args.min_len].index
    tr = tr[tr.track.isin(cand) & tr.team.isin(["us", "them"])]
    picks = {}
    for tid, g in tr.groupby("track"):
        pk = pick_crops(g, persons[persons.frame.isin(g.frame)], k=6)
        if len(pk):
            picks[tid] = pk
        if args.limit and len(picks) >= args.limit:
            break
    by_frame: dict[int, list] = {}
    for tid, pk in picks.items():
        for _, r in pk.iterrows():
            by_frame.setdefault(int(r.frame), []).append((tid, r))
    need = sorted(by_frame)
    print(f"{len(picks)} tracklets, {len(need)} frames to decode", flush=True)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise OSError(f"Cannot open video: {args.video}")
    # keep only small jersey crops, not full frames: (idx, frame, crop or None when the torso is not legible)
    crops: dict = {tid: [] for tid in picks}
    pose = None if args.no_pose else PoseGate()
    fi = 0
    try:
        while need and fi <= need[-1]:
            if fi in by_frame:
                ok, f = cap.read()
                if not ok:
                    raise OSError(f"Cannot decode requested frame {fi}: {args.video}")
                for tid, r in by_frame[fi]:
                    if pose is None:
                        c = upper_body(f, r)
                        if c is not None:
                            crops[tid].append([int(r.name), fi, c])
                    else:
                        pc = person_crop(f, r)
                        if pc is not None:
                            crops[tid].append([int(r.name), fi, None])
                            pose.add(pc, crops[tid][-1])
            elif not cap.grab():
                raise OSError(f"Video ended before requested frame {need[-1]}")
            fi += 1
    finally:
        cap.release()
    if pose is not None:
        pose.flush()
        n = sum(len(v) for v in crops.values())
        print(f"pose gate: {pose.legible} of {n} crops show a legible torso", flush=True)
    reader = JerseyReader()
    out = {}
    debug = out_path.parent / "jersey_debug"
    debug.mkdir(exist_ok=True)
    for i, tid in enumerate(picks):
        cs = crops[tid]
        if not cs:
            continue
        recs = []
        for idx, frame, c in cs:
            read, conf = reader.read(c) if c is not None else ("none", 0.0)
            recs.append(dict(idx=idx, frame=frame, read=read, conf=round(conf, 4), legible=c is not None))
        out[int(tid)] = rec = tracklet_record(recs)
        shown = [c for _, _, c in cs if c is not None]
        if i < 60 and shown:
            strip = np.hstack([cv2.resize(c, (128, 256)) for c in shown])
            cv2.imwrite(str(debug / f"{tid}_{rec['number']}_{'-'.join(rec['reads'])}.jpg"), strip)
        if i % 100 == 0:
            print(i, tid, rec["number"], rec["reads"], flush=True)
    out_path.write_text(json.dumps(out, indent=0))
    print(pd.Series({k: v["number"] for k, v in out.items()}).value_counts().head(30))


if __name__ == "__main__":
    main()
