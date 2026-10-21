import numpy as np
import pandas as pd
import pytest

from hoop_tape_miner import build_tracks as bt

TEAMS = {"navy": "us", "teal": "them", "ref": "ref"}


def _walker(n=60, y=5.0, p_navy=0.9, unsure=(), flip=(), start=0):
    """One player walking along x at 1 m/s, sampled at 10 fps (frame step 6), with class probabilities."""
    rows = []
    for k in range(n):
        f = (start + k) * 6
        pn = 0.5 if k in unsure else (1 - p_navy if k in flip else p_navy)
        rows.append(dict(frame=f, t=f / 60, cx=2.0 + 0.1 * k, cy=y, conf=0.9, x1=0.0, y1=0.0, x2=40.0, y2=100.0,
                         prob_navy=pn, prob_teal=1 - pn - 0.02, prob_ref=0.02))
    return rows


def _frame(rows):
    p = pd.DataFrame(rows)
    p["colour"] = bt.hard_colour(p, min_prob=0.7)
    return p


def test_hard_colour_is_argmax_above_the_cut_else_unk():
    p = pd.DataFrame(dict(prob_navy=[0.9, 0.5, 0.1], prob_teal=[0.05, 0.45, 0.8], prob_ref=[0.05, 0.05, 0.1]))
    assert bt.hard_colour(p, min_prob=0.7).tolist() == ["navy", "unk", "teal"]


def test_tracklet_team_is_the_mean_probability():
    p = pd.DataFrame(dict(track=[1, 1, 1, 2, 2], prob_navy=[0.9, 0.4, 0.8, 0.5, 0.4],
                          prob_teal=[0.05, 0.55, 0.1, 0.45, 0.5], prob_ref=[0.05, 0.05, 0.1, 0.05, 0.1]))
    lab = bt.tracklet_colours(p, min_prob=0.5)
    assert lab[1] == "navy" and lab[2] == "unk"     # track 2: mean 0.45 / 0.475, nobody above 0.5


def test_joint_tracking_keeps_unsure_detections_in_the_track():
    p = _frame(_walker(unsure=range(20, 32)))
    joint = bt.track_people(p, TEAMS, fps=10, mode="joint")
    split = bt.track_people(p, TEAMS, fps=10, mode="colour")
    # ByteTrack reports a new track from its second frame on, so 59 of 60 rows
    assert len(joint) == 59 and joint.track.nunique() == 1 and (joint.team == "us").all()
    assert len(split) <= 47                       # the colour split never tracks the 12 "unk" detections


def test_joint_tracking_survives_a_one_frame_colour_flip():
    p = _frame(_walker(flip={30}))
    joint = bt.track_people(p, TEAMS, fps=10, mode="joint")
    split = bt.track_people(p, TEAMS, fps=10, mode="colour")
    assert joint.track.nunique() == 1 and len(joint) == 59
    assert (split.team == "them").sum() <= 1 and (split.team == "us").sum() >= 57


def test_two_teams_tracked_jointly_get_their_own_team():
    rows = _walker(y=3.0) + [dict(r, prob_navy=0.05, prob_teal=0.93) for r in _walker(y=9.0)]
    out = bt.track_people(_frame(rows), TEAMS, fps=10, mode="joint")
    assert out.track.nunique() == 2
    assert sorted(out.groupby("track").team.first()) == ["them", "us"]
    assert {"cx_s", "cy_s", "colour"} <= set(out.columns)


def test_unknown_tracking_mode_fails():
    with pytest.raises(ValueError):
        bt.track_people(_frame(_walker()), TEAMS, fps=10, mode="nope")
