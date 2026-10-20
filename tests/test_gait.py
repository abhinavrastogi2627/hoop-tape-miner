"""2D gait metrics (gait.py) on synthetic side-view runners: contacts, step, layup and dribble metrics, validation."""
import numpy as np

from hoop_tape_miner import gait as G
from hoop_tape_miner import training as T

LEG = 160.0     # hip y 300, floor y 460
FLOOR = 460.0
TORSO = 100.0


def runner(fps=30, dur=3.0, step_t=1 / 3, step_len=0.8, lean=10.0, ahead=0.2, contact=0.15, lift=0.5,
           steps=None, hip_drop_at=None, drop=0.0, direction=1):
    """Side-view keypoints (N,17,2) and t. Touchdowns every `step_t` s alternating L/R, each `step_len` leg lengths
    after the previous one (or the list `steps`), touching down `ahead` leg lengths in front of the hip; the stance
    ankle stays put for `contact` s, then swings linearly in x with a sine lift. Hip sinks `drop` leg lengths while
    the contact index `hip_drop_at` is on the ground. direction -1 mirrors x."""
    t = np.arange(0, dur, 1 / fps)
    n_td = int(dur / step_t) + 4
    lens = list(steps) if steps is not None else [step_len] * n_td
    lens = [step_len, step_len] + lens  # two touchdowns before t=0 so both feet start planted
    td_t = np.array([(k - 2) * step_t for k in range(len(lens))])
    td_x = 400 + np.cumsum(np.array(lens) * LEG) - 2 * step_len * LEG
    feet = np.array([k % 2 for k in range(len(lens))])  # 0 = L, 1 = R
    hip_x = np.interp(t, td_t, td_x - ahead * LEG)
    hip_y = np.full(len(t), 300.0)
    if hip_drop_at is not None:
        k = hip_drop_at + 2
        hip_y[(t >= td_t[k] - 1e-9) & (t < td_t[k] + contact - 1e-9)] += drop * LEG
    kp = np.zeros((len(t), 17, 2))
    for f, (an, kn) in enumerate(((T.L_AN, T.L_KN), (T.R_AN, T.R_KN))):
        own = np.flatnonzero(feet == f)
        for i, ti in enumerate(t):
            j = own[np.searchsorted(td_t[own], ti + 1e-9, side="right") - 1]
            nxt = own[own > j]
            if ti - td_t[j] < contact - 1e-9 or not len(nxt):
                x, y = td_x[j], FLOOR
            else:
                n = nxt[0]
                s = (ti - td_t[j] - contact) / (td_t[n] - td_t[j] - contact)
                x, y = td_x[j] + (td_x[n] - td_x[j]) * s, FLOOR - lift * LEG * np.sin(np.pi * s)
            kp[i, an] = (x, y)
            kp[i, kn] = ((hip_x[i] + x) / 2 + 0.1 * LEG, (hip_y[i] + y) / 2)
    r = np.radians(lean)
    for h in (T.L_HIP, T.R_HIP):
        kp[:, h] = np.c_[hip_x, hip_y]
    for s in (T.L_SH, T.R_SH):
        kp[:, s] = np.c_[hip_x + np.sin(r) * TORSO, hip_y - np.cos(r) * TORSO]
    kp[:, T.NOSE] = np.c_[hip_x + np.sin(r) * TORSO * 1.4, hip_y - np.cos(r) * TORSO * 1.4]
    for w, e in ((T.L_WR, T.L_EL), (T.R_WR, T.R_EL)):
        kp[:, e] = kp[:, T.L_SH] + (0, 50)
        kp[:, w] = kp[:, T.L_SH] + (10, 95)
    if direction < 0:
        kp[..., 0] = 2000 - kp[..., 0]
    return t, kp, np.ones(kp.shape[:2]), td_t[2:], feet[2:]


def test_contacts_found():
    t, kp, conf, td_t, feet = runner()
    c = G.foot_contacts(t, kp, conf)
    assert len(c) == 8  # touchdowns at 1/3 .. 8/3 s; the one at t=0 starts the clip (onset unknown) and is dropped
    assert [x["foot"] for x in c] == ["R", "L"] * 4
    for x, k in zip(c, range(1, 9)):
        assert abs(x["on"] - k / 3) <= 1 / 30 + 1e-9


def test_direction_mirror():
    t, kp, conf, *_ = runner(lean=15, ahead=0.25)
    t2, kp2, conf2, *_ = runner(lean=15, ahead=0.25, direction=-1)
    assert G.direction(t, kp) == 1 and G.direction(t2, kp2) == -1
    a = G.clip_metrics(G.step_metrics(t, kp, conf, G.foot_contacts(t, kp, conf)), 30)
    b = G.clip_metrics(G.step_metrics(t2, kp2, conf2, G.foot_contacts(t2, kp2, conf2)), 30)
    for k in ("trunk_lean", "touchdown_ahead", "shin", "step_len", "knee_lift"):
        assert abs(a[k]["mean"] - b[k]["mean"]) < 1e-6, k


def test_lean_and_touchdown():
    t, kp, conf, *_ = runner(lean=20, ahead=0.3, step_len=0.9)
    assert abs(G.leg_length(kp) - LEG) < 1e-6
    m = G.clip_metrics(G.step_metrics(t, kp, conf, G.foot_contacts(t, kp, conf)), 30)
    assert abs(m["trunk_lean"]["first3"] - 20) <= 3
    assert abs(m["touchdown_ahead"]["first3"] - 0.3) <= 0.05
    assert abs(m["step_len"]["mean"] - 0.9) <= 0.02
    assert abs(m["cadence_spm"] - 180) <= 2


def test_contact_time_needs_100fps():
    t, kp, conf, *_ = runner(fps=30)
    assert all(s["contact_s"] is None for s in G.step_metrics(t, kp, conf, G.foot_contacts(t, kp, conf)))
    t, kp, conf, *_ = runner(fps=120)
    st = [s for s in G.step_metrics(t, kp, conf, G.foot_contacts(t, kp, conf)) if s["contact_s"] is not None]
    assert st and all(abs(s["contact_s"] - 0.15) <= 1 / 120 + 1e-9 for s in st)


def test_contacts_gap_no_invention():
    t, kp, conf, *_ = runner()
    gap = (t >= 1.0) & (t < 1.5)
    kp[gap] = np.nan
    conf[gap] = 0
    c = G.foot_contacts(t, kp, conf)
    assert not [x for x in c if 1.0 - 1e-9 <= x["on"] <= 1.5 + 1 / 30 + 1e-9]
    assert c  # the steps outside the gap are still found


def test_layup_penultimate():
    steps = [0.8, 0.8, 0.8, 0.8, 0.8 * 1.3, 0.7]  # touchdowns at 0, .3, .6, .9, 1.2 (penultimate), 1.5 (take-off)
    t, kp, conf, td_t, feet = runner(step_t=0.3, dur=2.0, steps=steps, hip_drop_at=4, drop=0.08)
    c = G.foot_contacts(t, kp, conf)
    lay = G.layup_metrics(t, kp, conf, c, release_t=1.7)
    assert abs(lay["penultimate_ratio"] - 1.3) <= 0.05
    assert abs(lay["hip_drop"] - 0.08) <= 0.02
    assert lay["takeoff_foot"] == ("L" if feet[5] == 0 else "R")
    assert len(lay["last3_len"]) == 3
    assert lay["free_knee"] is not None


def test_dribble_bounces():
    t = np.arange(0, 4, 1 / 30)
    kp = np.zeros((len(t), 17, 2))
    kp[:, [T.L_HIP, T.R_HIP]] = (500, 300)
    kp[:, [T.L_AN, T.R_AN]] = (500, 460)
    ball = np.c_[np.full(len(t), 520), 380 + 70 * np.cos(2 * np.pi * 2 * t)]  # 2 bounces/s, top at y=310
    d = G.dribble_metrics(t, kp, ball)
    assert 7 <= d["bounces"] <= 8
    assert abs(d["ball_top_vs_hip"] - (FLOOR - 310) / LEG) <= 0.02  # 1.0 = hip height
    assert d["bounces_per_10m"] is None


def test_compare_and_gate():
    lab = [{"on": 1.0}, {"on": 1.3}, {"on": 1.6}, {"on": 1.9}]
    det = [{"on": 1.02}, {"on": 1.3}, {"on": 1.57}, {"on": 2.5}]
    r = G.compare_contacts(det, lab, tol_s=0.1)
    assert (r["matched"], r["missed"], r["extra"]) == (3, 1, 1)
    assert abs(r["mae_s"] - (0.02 + 0 + 0.03) / 3) < 1e-9
    assert r["recall"] == 0.75 and r["precision"] == 0.75
    assert not G.gate(r, 30)
    ok = G.compare_contacts(det[:3], lab[:3], tol_s=0.1)
    assert G.gate(ok, 30) and not G.gate(ok, 120)  # 0.017 s MAE > 1.5 frames at 120 fps
