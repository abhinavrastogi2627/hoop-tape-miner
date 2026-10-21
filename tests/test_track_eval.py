import json

import numpy as np
import pandas as pd
import pytest

from hoop_tape_miner import track_eval as te


def _tracks(rows):
    """rows: (track, frame, team, x1) -> tracks.pkl-like frame (10 fps, 60 fps video: frame step 6)."""
    df = pd.DataFrame(rows, columns=["track", "frame", "team", "x1"])
    df["y1"] = 100.0
    df["x2"] = df.x1 + 40
    df["y2"] = 200.0
    df["t"] = df.frame / 60
    return df


def test_read_mot_keeps_considered_rows_only(tmp_path):
    p = tmp_path / "gt.txt"
    p.write_text("1,1,10,20,30,40,1,1,1\n1,2,50,20,30,40,0,1,1\n2,1,12,20,30,40,1,1,0.5\n")
    gt = te.read_mot(p)
    assert list(gt.columns[:6]) == ["frame", "id", "x", "y", "w", "h"]
    assert len(gt) == 2 and set(gt.id) == {1}


def test_tracks_to_mot_window_and_one_based_ids():
    tr = _tracks([(0, 6, "us", 10), (0, 12, "us", 12), (5, 12, "them", 90), (5, 600, "them", 90)])
    mot = te.tracks_to_mot(tr, frame0=6, frame1=60)
    assert mot.frame.tolist() == [6, 12, 12]
    assert (mot.id > 0).all() and mot.id.nunique() == 2
    assert mot.w.iloc[0] == 40 and mot.h.iloc[0] == 100


def test_mot_prelabels_of_a_sampled_clip_round_trip(tmp_path):
    tr = _tracks([(0, 720, "us", 10), (0, 726, "us", 12), (0, 729, "us", 13), (5, 732, "them", 90)])
    p = tmp_path / "pre.txt"
    te.write_mot(te.tracks_to_mot(tr, 720, 800), p, frame0=720, step=6)
    back = te.read_mot(p)
    assert back.frame.tolist() == [1, 2, 3]                       # frame 729 is off the 10 fps grid
    assert te.gt_to_video_frames(back, 12.0, 10, 60).frame.tolist() == [720, 726, 732]


def test_gt_frames_map_to_video_frames():
    gt = pd.DataFrame(dict(frame=[1, 2, 3], id=1, x=0.0, y=0.0, w=1.0, h=1.0))
    # a 10 fps clip cut at 12.0 s of a 60 fps video: clip frame k -> video frame 720 + 6 (k - 1)
    assert te.gt_to_video_frames(gt, start_s=12.0, gt_fps=10, video_fps=60).frame.tolist() == [720, 726, 732]


def _mot(rows):
    return pd.DataFrame(rows, columns=["frame", "id", "x", "y", "w", "h"])


def test_perfect_tracking_scores_one():
    pytest.importorskip("trackeval")
    gt = _mot([(f, i, 100 * i, 0, 40, 80) for f in range(1, 11) for i in (1, 2)])
    s = te.score_mot(gt, gt.assign(id=gt.id + 10))
    assert s["HOTA"] == pytest.approx(1.0) and s["IDF1"] == pytest.approx(1.0) and s["IDSW"] == 0


def test_identity_switch_lowers_idf1_and_hota_not_detection():
    pytest.importorskip("trackeval")
    gt = _mot([(f, i, 100 * i, 0, 40, 80) for f in range(1, 11) for i in (1, 2)])
    pred = gt.copy()
    late = pred.frame > 5
    pred.loc[late, "id"] = 3 - pred.loc[late, "id"]   # the two ids swap half way
    s = te.score_mot(gt, pred)
    assert s["IDSW"] == 2
    assert s["IDF1"] == pytest.approx(0.5)
    assert s["DetA"] == pytest.approx(1.0) and s["HOTA"] < 0.8


def test_score_only_on_given_frames():
    pytest.importorskip("trackeval")
    gt = _mot([(f, 1, 0, 0, 40, 80) for f in range(1, 7)])
    pred = gt[gt.frame % 2 == 0]      # the tracker only sampled even frames
    s = te.score_mot(gt, pred, frames=set(pred.frame))
    assert s["frames"] == 3 and s["HOTA"] == pytest.approx(1.0)


def test_proxy_metrics_lengths_coverage_conflicts_and_over_five():
    rows = []
    for k in range(6):          # six "us" tracks alive in frames 0..19 (one too many), ref ignored
        rows += [(k, f, "us", 10 * k) for f in range(0, 20 * 6, 6)]
    rows += [(9, f, "ref", 500) for f in range(0, 20 * 6, 6)]
    tr = _tracks(rows)
    numbers = {0: "4", 1: "4", 2: "7"}   # tracks 0 and 1 both claim #4 at the same time
    reads = {0: ["4", "4", "9", "9"], 1: ["4", "none"], 2: ["7", "7", "7"]}
    m = te.proxy_metrics(tr, numbers, reads, fps=10)
    assert m["tracklets"] == 6
    assert m["median_len_s"] == pytest.approx(2.0)
    assert m["id_coverage"] == pytest.approx(3 / 6)
    assert m["mixed_tracks"] == 1                 # track 0: two numbers, each read twice
    assert m["number_conflict_frames"] == pytest.approx(1.0)
    assert m["over5_frames"] == pytest.approx(1.0)


def test_proxy_metrics_cli_on_a_tiny_run(tmp_path):
    tr = _tracks([(0, f, "us", 10) for f in range(0, 120, 6)] + [(1, f, "them", 90) for f in range(0, 60, 6)])
    tr["number"] = tr.track.map({0: "4"})
    tr.to_pickle(tmp_path / "tracks.pkl")
    (tmp_path / "jersey.json").write_text(json.dumps({"0": {"number": "4", "reads": ["4", "4"]}}))
    np.savez(tmp_path / "camera.npz", frame=np.arange(0, 120, 6), t=np.arange(0, 120, 6) / 60,
             quality=np.zeros(20), fps=np.float64(10))
    out = tmp_path / "eval.json"
    te.main(["--run", str(tmp_path), "--out", str(out)])
    m = json.loads(out.read_text())["proxy"]
    assert m["tracklets"] == 2 and m["id_coverage"] == pytest.approx(20 / 30)
