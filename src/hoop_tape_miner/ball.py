"""Ball geometry (camera pose from the court homography) and the ball-track cleanup.

    hoop-tape-miner ball-track --run RUN [--video V] [--out RUN/ball_track.pkl]

The camera pose comes from the per-frame court homography alone (camera.npz H, court -> image): with the principal
point at the image centre and square pixels, the two court-plane columns of H fix the focal length and the rotation,
so a 3D point such as the rim (hoop centre at 3.05 m) projects into every calibrated frame. No rim detector needed.

ball-track turns extract's per-frame ball candidates into one track (coach_features.clean_ball: motion-consistent
tracklets, static objects dropped, short gaps interpolated), smooths each tracklet with a constant-velocity Kalman
filter + RTS smoother that rejects outliers by innovation, and adds the distance from the ball to each rim in metres
(measured in the camera-facing plane through the hoop). Writes ball_track.pkl and ball_track.json (quality).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .camera import sampled_fps
from .coach_features import ball_quality, clean_ball, project_balls
from .court import hoop_xy

RIM_Z = 3.05  # rim height (m)
BALL_D = 0.24  # ball diameter (m)
SIDES = ("left", "right")


# --- camera ---------------------------------------------------------------------------------------------------

def camera_from_homography(H: np.ndarray, size=(1280, 720)) -> tuple[np.ndarray, float] | None:
    """3x4 projection P (court metres + height z up -> image px) and focal length from a court -> image homography.

    Assumes square pixels and the principal point at the image centre. f^2 follows from the two rotation
    constraints (r1 . r2 = 0, |r1| = |r2|) by least squares; None when they have no positive solution (degenerate
    or non-finite H). z is oriented so that a point above the floor projects higher in the image.
    """
    H = np.asarray(H, float)
    if H.shape != (3, 3) or not np.isfinite(H).all():
        return None
    w, h = size
    T = np.array([[1, 0, w / 2], [0, 1, h / 2], [0, 0, 1.0]])
    A = np.linalg.inv(T) @ H
    h1, h2 = A[:, 0], A[:, 1]
    M = np.array([[h1[0] * h2[0] + h1[1] * h2[1]], [h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2]])
    b = -np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    u = float(np.linalg.lstsq(M, b, rcond=None)[0][0])
    if not np.isfinite(u) or u <= 0:
        return None
    f = 1 / np.sqrt(u)
    Ki = np.diag([1 / f, 1 / f, 1.0])
    r1, r2, t = Ki @ h1, Ki @ h2, Ki @ A[:, 2]
    lam = (np.linalg.norm(r1) + np.linalg.norm(r2)) / 2
    if lam <= 0:
        return None
    r1, r2, t = r1 / lam, r2 / lam, t / lam
    P = T @ np.diag([f, f, 1.0]) @ np.c_[r1, r2, np.cross(r1, r2), t]
    hx, hy = hoop_xy("left")
    q = project3(P, np.array([[hx, hy, 0.0], [hx, hy, RIM_Z]]))
    if q[1, 1] > q[0, 1]:  # "up" went down the image: flip z
        P[:, 2] *= -1
    return P, float(f)


def project3(P: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Project Nx3 points (x, y, z metres) with a 3x4 P to Nx2 pixels."""
    X = np.asarray(X, float)
    p = np.c_[X, np.ones(len(X))] @ P.T
    return p[:, :2] / p[:, 2:3]


def camera_centre(P: np.ndarray) -> np.ndarray:
    return -np.linalg.solve(P[:, :3], P[:, 3])


def rim_view(P: np.ndarray, side: str) -> tuple[float, float, float]:
    """(u, v, px_per_m) of the rim centre: its pixel and the image scale at the hoop."""
    hx, hy = hoop_xy(side)
    q = project3(P, np.array([[hx, hy, RIM_Z], [hx, hy + 0.5, RIM_Z]]))
    return float(q[0, 0]), float(q[0, 1]), float(np.hypot(*(q[1] - q[0])) / 0.5)


def facing_grid(P: np.ndarray, side: str, us: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """Pixel coordinates (len(zs), len(us), 2) of a plane through the hoop centre facing the camera (its lateral
    axis is horizontal and perpendicular to the camera -> hoop direction)."""
    U, Z = np.meshgrid(us, zs)
    return facing_points(P, side, U.ravel(), Z.ravel()).reshape(len(zs), len(us), 2)


def facing_points(P: np.ndarray, side: str, u, z) -> np.ndarray:
    """Pixels (N, 2) of points (u lateral m, z height m) in the camera-facing plane through the hoop centre."""
    hx, hy = hoop_xy(side)
    c = camera_centre(P)
    d = np.array([hx - c[0], hy - c[1]])
    d /= np.linalg.norm(d)
    lat = np.array([-d[1], d[0]])
    u, z = np.asarray(u, float), np.asarray(z, float)
    return project3(P, np.c_[hx + u * lat[0], hy + u * lat[1], z])


def cameras(cam: dict, size=(1280, 720)) -> dict[int, np.ndarray]:
    """{sampled frame: P} for every frame of camera.npz with a usable homography."""
    out = {}
    for f, H in zip(np.asarray(cam["frame"]), np.asarray(cam["H"], float)):
        r = camera_from_homography(H, size)
        if r is not None:
            out[int(f)] = r[0]
    return out


# --- ball track -----------------------------------------------------------------------------------------------

def smooth_tracklet(t: np.ndarray, xy: np.ndarray, acc: float = 3000.0, meas: float = 6.0,
                    gate: float = 4.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Constant-velocity Kalman filter + RTS smoother over one tracklet (image px).

    acc: white-acceleration noise (px/s^2), meas: measurement noise (px), gate: innovation gate in sigmas. A
    measurement outside the gate is not used (outlier) and its row is filled from the smoothed state.
    Returns (smoothed xy, velocity, outlier mask).
    """
    n = len(t)
    xs = np.zeros((n, 4))
    Ps = np.zeros((n, 4, 4))
    xp_all = np.zeros((n, 4))
    Pp_all = np.zeros((n, 4, 4))
    Fs = np.zeros((n, 4, 4))
    out = np.zeros(n, bool)
    Hm = np.array([[1, 0, 0, 0], [0, 1, 0, 0.0]])
    R = np.eye(2) * meas ** 2
    x = np.array([xy[0, 0], xy[0, 1], 0.0, 0.0])
    P = np.diag([meas ** 2, meas ** 2, 1e6, 1e6])
    for i in range(n):
        dt = t[i] - t[i - 1] if i else 0.0
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        q = acc ** 2
        Q = q * np.array([[dt ** 4 / 4, 0, dt ** 3 / 2, 0], [0, dt ** 4 / 4, 0, dt ** 3 / 2],
                          [dt ** 3 / 2, 0, dt ** 2, 0], [0, dt ** 3 / 2, 0, dt ** 2]])
        x, P = F @ x, F @ P @ F.T + Q
        xp_all[i], Pp_all[i], Fs[i] = x, P, F
        z = xy[i]
        if np.isfinite(z).all():
            S = Hm @ P @ Hm.T + R
            y = z - Hm @ x
            if i and float(y @ np.linalg.solve(S, y)) > gate ** 2:
                out[i] = True
            else:
                K = P @ Hm.T @ np.linalg.inv(S)
                x, P = x + K @ y, (np.eye(4) - K @ Hm) @ P
        xs[i], Ps[i] = x, P
    for i in range(n - 2, -1, -1):  # RTS
        C = Ps[i] @ Fs[i + 1].T @ np.linalg.inv(Pp_all[i + 1])
        xs[i] = xs[i] + C @ (xs[i + 1] - xp_all[i + 1])
        Ps[i] = Ps[i] + C @ (Ps[i + 1] - Pp_all[i + 1]) @ C.T
    return xs[:, :2], xs[:, 2:], out


def ball_track(dets: pd.DataFrame, cam: dict | None, size=(1280, 720), **clean_kw) -> pd.DataFrame:
    """One smoothed ball per frame from extract's candidates (see module doc).

    Returns clean_ball's columns plus sx, sy (smoothed px), vx, vy (px/s), outlier, and when cam is given
    d_left / d_right (ball -> rim centre, metres in the camera-facing plane through the hoop) and h_left / h_right
    (height of the ball above the rim in that plane, metres; NaN without a usable camera).
    """
    if cam is not None:
        dets = project_balls(dets, cam)
    b = clean_ball(dets, **clean_kw)
    b = b.assign(sx=np.nan, sy=np.nan, vx=np.nan, vy=np.nan, outlier=False)
    for _, g in b.groupby("tracklet"):
        g = g.sort_values("t")
        meas = g[["px", "py"]].to_numpy(float)
        meas[g.interp.to_numpy()] = np.nan  # interpolated rows are filled by the smoother, not measured
        s, v, o = smooth_tracklet(g.t.to_numpy(float), meas)
        b.loc[g.index, ["sx", "sy"]] = s
        b.loc[g.index, ["vx", "vy"]] = v
        b.loc[g.index, "outlier"] = o
    b = b[~b.outlier].reset_index(drop=True)
    for s in SIDES:
        b["d_" + s] = np.nan
        b["h_" + s] = np.nan
    if cam is not None and len(b):
        Ps = cameras(cam, size)
        for i, f in enumerate(b.frame.to_numpy()):
            P = Ps.get(int(f))
            if P is None:
                continue
            for s in SIDES:
                u, v, k = rim_view(P, s)
                b.loc[i, "d_" + s] = np.hypot(b.sx[i] - u, b.sy[i] - v) / k
                b.loc[i, "h_" + s] = (v - b.sy[i]) / k
    return b


# --- CLI ------------------------------------------------------------------------------------------------------

def video_size(video) -> tuple[int, int]:
    cap = cv2.VideoCapture(str(video))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return (w, h) if w and h else (1280, 720)


def track_main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner ball-track", description="Smoothed ball track + rim distances")
    ap.add_argument("--run", required=True, help="run folder with detections.pkl (and camera.npz)")
    ap.add_argument("--video", help="video, only to read the frame size (default 1280x720)")
    ap.add_argument("--out", help="default: RUN/ball_track.pkl (a .json quality summary is written next to it)")
    a = ap.parse_args(argv)
    run = Path(a.run)
    out = Path(a.out) if a.out else run / "ball_track.pkl"
    size = video_size(a.video) if a.video else (1280, 720)
    dets = pd.read_pickle(run / "detections.pkl")
    cam = dict(np.load(run / "camera.npz")) if (run / "camera.npz").exists() else None
    b = ball_track(dets, cam, size)
    frames = dets.frame.unique()
    q = {"fps": sampled_fps(run), "raw": ball_quality(dets, 0.3), "track": ball_quality(b, 0.3, frames=frames),
         "track_detected_only": ball_quality(b[~b.interp], 0.3, frames=frames),
         "near_rim_frames": int((np.fmin(b.d_left, b.d_right) <= 1.5).sum()) if len(b) else 0}
    out.parent.mkdir(parents=True, exist_ok=True)
    b.to_pickle(out)
    out.with_suffix(".json").write_text(json.dumps(q, indent=1), encoding="utf8")
    print(f"ball-track: {len(b)} frames -> {out}")
    print("quality:", json.dumps(q))


def main(argv=None):
    track_main(argv)


if __name__ == "__main__":
    main()
