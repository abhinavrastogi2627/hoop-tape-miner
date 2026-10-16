"""No-GPU tests for `calibrate` without a GUI (--grid / --points / --propagate) on a synthetic court video."""
import json

import cv2
import numpy as np
import pytest

from hoop_tape_miner import calibrate as cal
from hoop_tape_miner.camera import KeyframeBank
from hoop_tape_miner.court import COURT_POINTS, LENGTH, WIDTH, court_polylines, project

W, H_, FPS, SECS = 640, 360, 10, 8
QUAD = np.float32([[40, 330], [600, 330], [500, 90], [140, 90]])  # court corners (0,0) (28,0) (28,15) (0,15)
H_TRUE = cv2.getPerspectiveTransform(np.float32([[0, 0], [LENGTH, 0], [LENGTH, WIDTH], [0, WIDTH]]), QUAD)
_rng = np.random.default_rng(0)
SPECKLE = np.c_[_rng.uniform(-6, 34, 2500), _rng.uniform(-4, 22, 2500)]  # floor texture, court metres
NAMES = ["L_corner_near", "L_corner_far", "L_ft_near", "L_ft_far", "mid_far", "R_corner_near", "R_lane_base_far"]


def pan(t):
    """Ground-truth court->image homography at time t: the camera pans 8 px/s."""
    return np.array([[1, 0, -8.0 * (t - 4)], [0, 1, 0], [0, 0, 1]]) @ H_TRUE


def render(H):
    img = np.full((H_, W, 3), (50, 90, 140), np.uint8)
    for x, y in project(H, SPECKLE):
        if -5 < x < W + 5 and -5 < y < H_ + 5:
            cv2.circle(img, (int(x), int(y)), 2, (20, 40, 70), -1)
    for pl in court_polylines():
        cv2.polylines(img, [np.round(project(H, pl)).astype(np.int32)], False, (240, 240, 240), 2, cv2.LINE_AA)
    return img


def landmark_px(names, H, noise=0.0, seed=1):
    r = np.random.default_rng(seed)
    pts = project(H, np.float32([cal.LANDMARKS[n][0] for n in names])) + r.normal(0, noise, (len(names), 2))
    return [{"name": n, "px": [round(float(x), 1), round(float(y), 1)]} for n, (x, y) in zip(names, pts)]


def reproj(Ha, Hb):
    return float(np.median(np.linalg.norm(project(Ha, COURT_POINTS) - project(Hb, COURT_POINTS), axis=1)))


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("vid") / "court.mp4"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H_))
    assert vw.isOpened()
    for i in range(FPS * SECS):
        vw.write(render(pan(i / FPS)))
    vw.release()
    return str(path)


def run(args, capsys):
    try:
        code = cal.main(args)
    except SystemExit as e:
        code = e.code
    return code, capsys.readouterr().out


def write_points(path, pts_by_t):
    path.write_text(json.dumps(pts_by_t), encoding="utf-8")
    return str(path)


def test_grid_writes_images_and_lists_landmarks(video, tmp_path, capsys):
    code, out = run(["--video", video, "--times", "1,4", "--out", str(tmp_path), "--grid"], capsys)
    assert code == 0
    for t in ("1", "4"):
        g = cv2.imread(str(tmp_path / f"grid_{t}.jpg"))
        assert g is not None and g.shape[0] > H_ and g.shape[1] >= W  # landmark map appended below the frame
    assert "L_corner_near" in out and "(14.00, 15.00)" in out
    assert not (tmp_path / "keyframes.json").exists()


def test_fit_recovers_homography_from_noisy_points():
    img = render(H_TRUE)
    pts = landmark_px(NAMES, H_TRUE, noise=3.0)
    H, med, sup = cal.fit(img, pts)
    assert reproj(H, H_TRUE) < 1.5
    ok, line, worst = cal.report_line(4, pts, H, med, sup)
    assert ok and line.startswith("PASS t=4 points=7") and "worst:" in worst


def test_points_pass_writes_keyframes(video, tmp_path, capsys):
    pts = write_points(tmp_path / "points.json", {"4.0": landmark_px(NAMES, pan(4), noise=2.0)})
    code, out = run(["--video", video, "--times", "4", "--out", str(tmp_path), "--points", pts], capsys)
    assert code == 0 and "PASS t=4 " in out
    kf = json.loads((tmp_path / "keyframes.json").read_text())
    assert [k["t"] for k in kf] == [4.0] and kf[0]["source"] == "points"
    assert reproj(np.array(kf[0]["H"]), pan(4)) < 2 and (tmp_path / "ov_4.jpg").exists()


def test_wrong_point_is_weak_and_named(video, tmp_path, capsys):
    pts = landmark_px(NAMES, pan(4), noise=1.0)
    pts[3]["px"][0] += 70  # L_ft_far clicked 70 px off
    p = write_points(tmp_path / "points.json", {"4": pts})
    code, out = run(["--video", video, "--times", "4", "--out", str(tmp_path), "--points", p], capsys)
    assert code == 2 and "WEAK t=4 " in out
    assert out.split("worst: ")[1].startswith("L_ft_far=")
    assert json.loads((tmp_path / "keyframes.json").read_text()) == []
    assert (tmp_path / "ov_4.jpg").exists()  # overlay still written to show what is wrong


def test_missing_time_warns_and_continues(video, tmp_path, capsys):
    p = write_points(tmp_path / "points.json", {"4": landmark_px(NAMES, pan(4))})
    code, out = run(["--video", video, "--times", "2,4", "--out", str(tmp_path), "--points", p], capsys)
    assert code == 2 and "WARNING: no points for t=2" in out and "PASS t=4 " in out
    assert [k["t"] for k in json.loads((tmp_path / "keyframes.json").read_text())] == [4.0]


def test_propagate_backward_and_forward(video, tmp_path, capsys):
    p = write_points(tmp_path / "points.json", {"4": landmark_px(NAMES, pan(4), noise=2.0)})
    code, out = run(["--video", video, "--times", "4", "--out", str(tmp_path), "--points", p,
                     "--propagate", "1,7", "--step", "2"], capsys)
    assert code == 0, out
    kf = {k["t"]: k for k in json.loads((tmp_path / "keyframes.json").read_text())}
    assert sorted(kf) == [1.0, 4.0, 7.0] and kf[1.0]["source"] == kf[7.0]["source"] == "propagated"
    for t in (1.0, 7.0):
        assert reproj(np.array(kf[t]["H"]), pan(t)) < 2.5
        assert reproj(np.array(kf[4.0]["H"]), pan(t)) > 15  # really tracked, not the start frame's H


def test_propagate_unreachable_target_is_weak(video, tmp_path, capsys):
    p = write_points(tmp_path / "points.json", {"4": landmark_px(NAMES, pan(4))})
    code, out = run(["--video", video, "--times", "4", "--out", str(tmp_path), "--points", p,
                     "--propagate", "60"], capsys)
    assert code == 2 and "WEAK t=60" in out
    assert [k["t"] for k in json.loads((tmp_path / "keyframes.json").read_text())] == [4.0]


def test_keyframe_bank_uses_frame_size():
    bank = KeyframeBank()
    bank.add(cv2.cvtColor(render(H_TRUE), cv2.COLOR_BGR2GRAY), H_TRUE)
    assert bank.size == (W, H_)
    centre = project(np.linalg.inv(H_TRUE), np.array([[W / 2, H_ / 2]]))[0]
    assert np.allclose(bank.views[0][:2], centre)
