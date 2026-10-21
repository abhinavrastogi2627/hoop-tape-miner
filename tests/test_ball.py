"""Ball geometry (camera from the court homography), track smoothing, the rim-zone scanner and the review-sheet
ball layers, on synthetic data."""
import json

import numpy as np
import pandas as pd
import cv2

from hoop_tape_miner import ball as B
from hoop_tape_miner import rim_scan as RS
from hoop_tape_miner.court import hoop_xy

SIZE = (1280, 720)


def synth_camera(centre=(14.0, -9.0, 7.5), look=(14.0, 7.5, 0.0), f=1900.0, size=SIZE):
    """3x4 P for a camera at `centre` looking at `look` (court metres, z up), square pixels, centred principal
    point; image v grows downwards."""
    c, l = np.array(centre), np.array(look)
    zc = (l - c) / np.linalg.norm(l - c)  # optical axis
    xc = np.cross(zc, [0, 0, 1.0])
    xc /= np.linalg.norm(xc)  # image right
    yc = np.cross(zc, xc)  # image down
    R = np.stack([xc, yc, zc])
    K = np.array([[f, 0, size[0] / 2], [0, f, size[1] / 2], [0, 0, 1]])
    return K @ np.c_[R, -R @ c]


def homography(P):
    return P[:, [0, 1, 3]] / P[2, 3]


def test_camera_from_homography_recovers_focal_and_rim():
    for centre, look, f in (((14, -9, 7.5), (14, 7.5, 0), 1900.0), ((8, -6, 9), (4, 7.5, 0), 2400.0)):
        P = synth_camera(centre, look, f)
        got = B.camera_from_homography(homography(P), SIZE)
        assert got is not None
        P2, f2 = got
        assert abs(f2 - f) / f < 1e-6
        for side in B.SIDES:
            hx, hy = hoop_xy(side)
            want = B.project3(P, [[hx, hy, B.RIM_Z]])[0]
            assert np.allclose(B.project3(P2, [[hx, hy, B.RIM_Z]])[0], want, atol=1e-3)
            u, v, k = B.rim_view(P2, side)
            assert v < B.project3(P, [[hx, hy, 0.0]])[0][1]  # rim above the floor point
            assert 30 < k < 400
        assert np.allclose(B.camera_centre(P2), centre, atol=1e-6)


def test_camera_from_homography_rejects_bad_input():
    assert B.camera_from_homography(np.full((3, 3), np.nan)) is None
    assert B.camera_from_homography(np.eye(3)) is None  # no positive focal solution


def parabola(n=30, fps=10.0, noise=3.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fps
    x = 200 + 400 * t
    y = 500 - 600 * t + 450 * t ** 2
    return t, np.c_[x, y], np.c_[x, y] + rng.normal(0, noise, (n, 2))


def test_smooth_tracklet_reduces_noise_and_rejects_outlier():
    t, truth, meas = parabola()
    meas[12] += [120, -90]  # a jump to another object
    meas[[5, 6, 20]] = np.nan  # gaps (interpolated rows) are filled
    s, v, out = B.smooth_tracklet(t, meas)
    assert out[12] and out.sum() == 1
    ok = np.isfinite(meas).all(1) & ~out
    assert np.abs(s - truth)[ok].mean() < np.abs(meas - truth)[ok].mean()
    assert np.abs(s[[5, 6, 20, 12]] - truth[[5, 6, 20, 12]]).max() < 15
    assert np.all(v[3:-3, 0] > 300)  # moving right at ~400 px/s


def test_ball_track_adds_rim_distance():
    P = synth_camera()
    H = homography(P)
    hx, hy = hoop_xy("right")
    t = np.arange(20) / 10
    # a ball flying into the right rim: from 4 m out and 2.2 m up to the rim
    X = np.c_[hx - 4 + 4 * t / t[-1], np.full(20, hy), 2.2 + 0.85 * t / t[-1]]
    uv = B.project3(P, X)
    rows = [dict(frame=i * 6, t=float(t[i]), kind="ball", x1=u - 8, y1=v - 8, x2=u + 8, y2=v + 8, conf=0.7,
                 cx=np.nan, cy=np.nan) for i, (u, v) in enumerate(uv)]
    rows += [dict(frame=i * 6, t=float(t[i]), kind="person", x1=0, y1=0, x2=10, y2=10, conf=0.9, cx=1, cy=1)
             for i in range(20)]
    dets = pd.DataFrame(rows)
    cam = {"frame": np.arange(20) * 6, "t": t, "H": np.repeat(H[None], 20, 0)}
    b = B.ball_track(dets, cam, SIZE)
    assert len(b) == 20 and not b.outlier.any()
    assert b.d_right.iloc[-1] < 0.2 and b.d_right.iloc[0] > 3
    assert b.d_left.min() > 20
    assert abs(b.h_right.iloc[-1]) < 0.2 and b.h_right.iloc[0] < -0.5


def test_ball_blobs_keeps_ball_drops_lines():
    fg = np.zeros((60, 80), np.uint8)
    cv2.circle(fg, (20, 30), 4, 1, -1)  # ball: 0.24 m at 0.03 m per cell -> radius 4
    cv2.line(fg, (40, 5), (78, 55), 1, 2)  # an edge left by misregistration
    cv2.rectangle(fg, (60, 2), (78, 20), 1, -1)  # a player's arm / big blob
    got = RS.ball_blobs(fg, 0.03)
    assert len(got) == 1 and abs(got[0][0] - 20) < 1 and abs(got[0][1] - 30) < 1


def test_rim_scanner_finds_ball_over_textured_background():
    P = synth_camera(look=(5.0, 7.5, 1.5))  # panned to the left basket
    rng = np.random.default_rng(1)
    bg = cv2.GaussianBlur(rng.integers(60, 200, (SIZE[1], SIZE[0])).astype(np.uint8), (0, 0), 3)
    sc = RS.RimScanner(fps=30)
    hx, hy = hoop_xy("left")
    for i in range(40):  # background with a small camera jitter
        sh = np.float32([[1, 0, (i % 3) * 0.6], [0, 1, (i % 2) * 0.5]])
        img = cv2.warpAffine(bg, sh, SIZE, borderMode=cv2.BORDER_REFLECT)
        assert sc.feed(img, P, "left") == [] or i < 10
    ball3d = np.array([[hx + 0.3, hy - 0.2, 3.6]])
    u, v = B.project3(P, ball3d)[0]
    r = 0.12 * B.rim_view(P, "left")[2]
    img = bg.copy()
    cv2.circle(img, (int(round(u)), int(round(v))), int(round(r)), 20, -1)
    got = sc.feed(img, P, "left")
    assert len(got) == 1
    gu, gz, _ = got[0]
    assert abs(gz - 3.6) < 0.1 and abs(gu) < 0.6
    assert sc.feed(img, None, "left") == [] and len(sc.buf["left"]) == 0  # lost camera resets


class FakeCap:
    """cv2.VideoCapture stand-in: 60 fps, grey 1280x720 frames."""

    def get(self, prop):
        return {cv2.CAP_PROP_FPS: 60.0, cv2.CAP_PROP_FRAME_WIDTH: 1280, cv2.CAP_PROP_FRAME_HEIGHT: 720}.get(prop, 0)

    def set(self, prop, v):
        pass

    def read(self):
        return True, np.full((720, 1280, 3), 90, np.uint8)


def test_sheets_draw_ball_trail_and_attempt_markers(tmp_path):
    from hoop_tape_miner import coach_review as CR
    P = synth_camera(look=(5.0, 7.5, 1.5))
    np.savez(tmp_path / "camera.npz", frame=np.arange(0, 600, 6), H=np.repeat(homography(P)[None], 100, 0))
    ball = pd.DataFrame({"t": [4.5, 4.7, 4.9, 5.0], "frame": [270, 282, 294, 300],
                         "sx": [500.0, 520, 540, 550], "sy": [300.0, 280, 270, 265]})
    ball.to_pickle(tmp_path / "ball_track.pkl")
    att = [{"t": 5.0, "side": "left", "team": "us", "label": "made", "points": 2,
            "arc": [[4.6, -0.8, 3.6], [4.8, -0.4, 3.5], [5.0, 0.0, 3.1]]},
           {"t": 60.0, "side": "right", "team": "them", "label": "likely miss", "points": None, "arc": []}]
    (tmp_path / "shot_proposals.json").write_text(json.dumps({"proposals": att}))
    b, a, cams = CR.load_ball_layers(tmp_path)
    assert len(b) == 4 and len(a) == 2 and len(cams["frames"]) == 100
    poss = pd.DataFrame({"start": [3.0], "end": [6.0], "side": ["left"], "offence": ["us"], "period": [1]})
    tracks = pd.DataFrame({"frame": [300], "x1": [0.0], "y1": [0.0], "x2": [1.0], "y2": [1.0], "team": ["x"],
                           "track": [1]})
    lay = dict(every=1.0, pre=0.0, post=0.0, tile=[640, 360], grid=[2, 2])
    plain = CR.build_sheets(FakeCap(), tracks, poss, {}, [], {}, tmp_path, lay)
    assert "cv_attempts" not in plain[0]
    grey = cv2.imread(str(tmp_path / plain[0]["sheets"][0])).astype(int)
    m = CR.build_sheets(FakeCap(), tracks, poss, {}, [], {}, tmp_path, lay, ball=b, attempts=a, cams=cams)
    assert [x["t"] for x in m[0]["cv_attempts"]] == [5.0] and m[0]["cv_attempts"][0]["label"] == "made"
    assert "CV attempts 1" not in str(plain) and m[0]["sheets"] == plain[0]["sheets"]
    drawn = cv2.imread(str(tmp_path / m[0]["sheets"][0])).astype(int)
    assert np.abs(drawn - grey).max() > 100  # trail and attempt marker drawn
    assert CR.load_ball_layers(tmp_path / "none") == (None, None, None)
    assert CR.attempt_text(att[0]) == "CV attempt? made +2"
    assert CR.attempt_text({"label": None}) == "CV attempt? unlabelled"
