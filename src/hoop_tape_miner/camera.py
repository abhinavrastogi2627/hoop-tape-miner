"""Per-frame court homography for a panning/zooming broadcast camera.

Strategy (no learned court model needed):
  1. propagate the previous frame's court->image homography with sparse optical flow
     on the background (player boxes masked out);
  2. snap it onto the painted court lines (court.refine_homography) to kill drift;
  3. if tracking is lost, relocalise against a bank of calibrated keyframes with SIFT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .court import refine_homography

DEFAULT_FPS = 10.0   # the sampling rate runs used before extract recorded it in camera.npz


def sample_step(video_fps: float, target_fps: float = DEFAULT_FPS) -> int:
    """Keep every `step`-th frame so that video_fps / step is as close as possible to target_fps
    (a tie keeps the higher rate). 25 fps -> 3 (8.3 fps), 60 -> 6, 29.97 -> 3, 24 -> 2 (12 fps)."""
    if video_fps <= 0 or target_fps <= 0:
        return 1
    lo = max(1, int(video_fps // target_fps))
    return min((lo, lo + 1), key=lambda s: (abs(video_fps / s - target_fps), s))


def sampled_fps(run) -> float:
    """Frames per second that extract kept (camera.npz "fps"); DEFAULT_FPS for runs written before it was
    recorded, or when camera.npz is missing."""
    p = Path(run) / "camera.npz"
    if not p.exists():
        return DEFAULT_FPS
    with np.load(p) as cam:
        return float(cam["fps"]) if "fps" in cam.files else DEFAULT_FPS


def _people_mask(shape, boxes, pad=6):
    m = np.zeros(shape[:2], np.uint8)
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(m, (int(x1) - pad, int(y1) - pad), (int(x2) + pad, int(y2) + pad), 255, -1)
    return m


@dataclass
class KeyframeBank:
    sift: cv2.SIFT = field(default_factory=lambda: cv2.SIFT_create(nfeatures=3000))
    frames: list = field(default_factory=list)  # (kp, des, H_court2img)
    views: list = field(default_factory=list)   # view descriptor per keyframe
    size: tuple = (1280, 720)                    # (w, h) of the frames, set by the first add()

    @staticmethod
    def view(H, size=(1280, 720)):
        """Court position of the image centre + horizontal extent: identifies a pan/zoom state."""
        from .court import project
        w, h = size
        c = project(np.linalg.inv(H), np.array([[w / 2, h / 2], [0.0, h / 2], [float(w), h / 2]]))
        return np.array([c[0, 0], c[0, 1], np.linalg.norm(c[2] - c[1])])

    def is_new_view(self, H, min_dist=1.5):
        v = self.view(H, self.size)
        return not self.views or min(np.linalg.norm(v - w) for w in self.views) > min_dist

    def add(self, gray, H, mask=None):
        if not self.frames:
            self.size = (gray.shape[1], gray.shape[0])
        kp, des = self.sift.detectAndCompute(gray, None if mask is None else 255 - mask)
        if des is not None and len(kp) > 100:
            self.frames.append((np.float32([k.pt for k in kp]), des, H.copy()))
            self.views.append(self.view(H, self.size))

    def localise(self, gray, mask=None):
        kp, des = self.sift.detectAndCompute(gray, None if mask is None else 255 - mask)
        if des is None or len(kp) < 50:
            return None, 0
        pts = np.float32([k.pt for k in kp])
        bf = cv2.BFMatcher(cv2.NORM_L2)
        best, best_n = None, 0
        for kpts, kdes, kH in self.frames:
            m = bf.knnMatch(des, kdes, k=2)
            good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < 0.75 * b.distance]
            if len(good) < 30:
                continue
            src = pts[[g.queryIdx for g in good]]
            dst = kpts[[g.trainIdx for g in good]]
            Hrel, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)  # frame -> keyframe
            n = int(inl.sum()) if inl is not None else 0
            if Hrel is not None and n > best_n:
                best, best_n = np.linalg.inv(Hrel) @ kH, n
        return best, best_n


class CourtCameraTracker:
    def __init__(self, bank: KeyframeBank, relocalise_after=5):
        self.bank = bank
        self.prev_gray = None
        self.H = None
        self.relocalise_after = relocalise_after
        self.unrefined = 0
        self.lost = 0
        self._prev_boxes = []

    def update(self, bgr, person_boxes=()):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        pmask = _people_mask(gray.shape, person_boxes)
        H_pred, how = None, "none"
        if self.H is not None and self.prev_gray is not None:
            feat_mask = 255 - _people_mask(gray.shape, self._prev_boxes)
            p0 = cv2.goodFeaturesToTrack(self.prev_gray, 800, 0.01, 8, mask=feat_mask)
            if p0 is not None and len(p0) > 40:
                p1, st, _ = cv2.calcOpticalFlowPyrLK(self.prev_gray, gray, p0, None, winSize=(21, 21), maxLevel=3)
                ok = st.ravel() == 1
                if ok.sum() > 40:
                    Hrel, inl = cv2.findHomography(p0[ok], p1[ok], cv2.RANSAC, 3.0)
                    if Hrel is not None and inl.sum() > 30:
                        H_pred, how = Hrel @ self.H, "flow"
        if (H_pred is None or self.unrefined >= self.relocalise_after) and self.bank.frames:
            H_sift, n = self.bank.localise(gray, pmask)
            if H_sift is not None:
                H_pred, how = H_sift, f"sift{n}"
        quality = 999.0
        if H_pred is not None:
            H_ref, med, sup = refine_homography(bgr, H_pred, ignore_mask=pmask)
            if sup >= 120 and med < 3.0 and _sane(H_ref, H_pred):
                self.H, quality = H_ref, med
                self.unrefined = 0
                if sup >= 300 and med < 1.5 and self.bank.is_new_view(self.H):
                    self.bank.add(gray, self.H, pmask)
            else:
                self.H = H_pred
                quality = 50.0
                self.unrefined += 1
            self.lost = 0
        else:
            # lost: no pose for this frame (extract stores NaN), and the old pose is not chained by flow later;
            # the next frame relocalises from the keyframe bank
            self.lost += 1
            self.H = None
        self.prev_gray = gray
        self._prev_boxes = list(person_boxes)
        return self.H, quality, how


def _sane(H_new, H_old, max_shift=60.0):
    """Reject refinements that jump far from the prediction (wrong-line snapping)."""
    from .court import project
    probe = np.array([[4, 4], [14, 7.5], [24, 4], [8, 12], [20, 12]], float)
    d = np.linalg.norm(project(H_new, probe) - project(H_old, probe), axis=1)
    return float(np.median(d)) < max_shift
