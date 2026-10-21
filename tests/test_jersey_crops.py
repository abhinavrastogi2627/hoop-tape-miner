import numpy as np
import pandas as pd

from hoop_tape_miner import jersey as js


def _pose(shoulder_w=40.0, conf=0.9):
    """17 COCO keypoints of an upright player: shoulders at y=50, hips at y=150, centred on x=100."""
    K = np.zeros((17, 2))
    C = np.full(17, conf)
    K[5], K[6] = (100 - shoulder_w / 2, 50), (100 + shoulder_w / 2, 50)
    K[11], K[12] = (100 - shoulder_w / 3, 150), (100 + shoulder_w / 3, 150)
    return K, C


def test_torso_box_spans_shoulders_to_hips_with_a_margin():
    K, C = _pose(shoulder_w=60)
    x1, y1, x2, y2 = js.torso_box(K, C, margin=0.1)
    assert (y1, y2) == (40, 160) and x1 == 60 and x2 == 140


def test_torso_box_rejects_a_side_on_or_unseen_torso():
    K, C = _pose(shoulder_w=10)                       # side-on: 10 px wide for a 100 px torso
    assert js.torso_box(K, C) is None
    K, C = _pose()
    C[11] = 0.1                                       # a hip hidden
    assert js.torso_box(K, C) is None


def test_pick_pose_takes_the_person_in_the_middle_of_the_crop():
    boxes = np.array([[0, 0, 30, 100], [40, 10, 90, 200], [150, 0, 200, 100]], float)
    assert js.pick_pose(boxes, (210, 130)) == 1
    assert js.pick_pose(np.zeros((0, 4)), (10, 10)) == -1


def test_person_crop_returns_offsets():
    img = np.zeros((300, 400, 3), np.uint8)
    r = pd.Series(dict(x1=100.0, y1=50.0, x2=150.0, y2=150.0))
    c, x0, y0 = js.person_crop(img, r)
    assert (x0, y0) == (95, 40) and c.shape[:2] == (120, 60)


def test_tracklet_record_votes_with_confidence_and_keeps_crops_in_time_order():
    recs = [dict(idx=3, frame=30, read="7", conf=0.95, legible=True),
            dict(idx=1, frame=10, read="7", conf=0.9, legible=True),
            dict(idx=2, frame=20, read="1", conf=0.3, legible=True),
            dict(idx=4, frame=40, read="none", conf=0.0, legible=False)]
    rec = js.tracklet_record(recs)
    assert rec["number"] == "7" and rec["reads"] == ["7", "1", "7", "none"]
    assert [c["idx"] for c in rec["crops"]] == [1, 2, 3, 4]
    assert js.crop_table({"5": rec}).idx.tolist() == [1, 2, 3, 4]
    low = [dict(r, conf=0.5) for r in recs[:2]]
    assert js.tracklet_record(low)["number"] == "none"        # two unsure reads are not enough
