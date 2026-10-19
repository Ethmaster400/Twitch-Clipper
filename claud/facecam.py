"""Automatic webcam-overlay detection.

1. Sample frames across the clip and run a face detector on each.
2. A facecam overlay shows the same face in the same place in most frames;
   faces in gameplay come and go. Keep the most persistent face, if any.
3. Estimate the overlay box around that face, then refine each side by looking
   for where the picture switches from "still" (webcam) to "moving" (gameplay).
   Sides with no clear border snap to the frame edge when close, as cams
   usually sit in a corner.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np

from .render import Rect

log = logging.getLogger("claud")

ANALYSIS_WIDTH = 960
MIN_FACE_FRAMES = 0.35      # face must appear in this share of sampled frames
MAX_FACE_HEIGHT = 0.4       # bigger faces mean a full-screen camera, not an overlay
SNAP_MARGIN = 0.08          # snap a border to the frame edge when this close
STRIP = 12                  # width in px of the strips compared on each side of a border


def _cv2():
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError("Facecam detection needs OpenCV: pip install 'opencv-python-headless<5'") from e
    return cv2


def sample_frames(video: Path, n: int = 16) -> list[np.ndarray]:
    """Grayscale frames spread evenly across the clip, resized to ANALYSIS_WIDTH."""
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for pos in np.linspace(total * 0.05, total * 0.95, n).astype(int) if total > 0 else []:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (ANALYSIS_WIDTH, round(h * ANALYSIS_WIDTH / w)), interpolation=cv2.INTER_AREA)
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()
    return frames


_cascades = None


def find_faces(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    global _cascades
    cv2 = _cv2()
    if _cascades is None:
        _cascades = [
            cv2.CascadeClassifier(cv2.data.haarcascades + name)
            for name in ("haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml")
        ]
    width = gray.shape[1]
    min_size = (max(16, int(width * 0.03)),) * 2
    faces = []
    for i, cascade in enumerate(_cascades):
        for x, y, w, h in cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=min_size):
            faces.append((int(x), int(y), int(w), int(h)))
        if i == 1:  # profile cascade only finds faces looking one way; try the mirror too
            for x, y, w, h in cascade.detectMultiScale(gray[:, ::-1], scaleFactor=1.1, minNeighbors=4, minSize=min_size):
                faces.append((int(width - x - w), int(y), int(w), int(h)))
    return faces


def persistent_face(faces_per_frame: list[list[tuple]], n_frames: int):
    """The face box seen in the same place in the most frames, or None."""
    best, best_frames = None, set()
    for seed in (f for faces in faces_per_frame for f in faces):
        sx, sy = seed[0] + seed[2] / 2, seed[1] + seed[3] / 2
        hits, members = set(), []
        for i, faces in enumerate(faces_per_frame):
            for f in faces:
                cx, cy = f[0] + f[2] / 2, f[1] + f[3] / 2
                if math.hypot(cx - sx, cy - sy) < 0.5 * seed[2] and 0.6 < f[2] / seed[2] < 1.6:
                    hits.add(i)
                    members.append(f)
        if len(hits) > len(best_frames):
            best, best_frames = members, hits
    if not best or len(best_frames) < max(3, math.ceil(MIN_FACE_FRAMES * n_frames)):
        return None
    return tuple(int(v) for v in np.median(np.array(best), axis=0))


def _estimate(face, width: int, height: int) -> list[float]:
    """Typical overlay: face is ~1/3 of the cam height, a bit above centre, cam ~3:2."""
    fx, fy, fw, fh = face
    cam_h = min(height, fh * 3.0)
    cam_w = min(width, cam_h * 1.5)
    left = fx + fw / 2 - cam_w / 2
    top = fy + fh / 2 - cam_h * 0.42
    left = min(max(0, left), width - cam_w)
    top = min(max(0, top), height - cam_h)
    return [left, top, left + cam_w, top + cam_h]


def _find_step(profile: np.ndarray, lo: int, hi: int, outside_before: bool) -> int | None:
    """Index where motion steps from high (outside) to low (inside), searched in [lo, hi)."""
    best, best_score = None, 0.0
    for i in range(max(lo, STRIP), min(hi, len(profile) - STRIP)):
        before, after = profile[i - STRIP : i].mean(), profile[i : i + STRIP].mean()
        outside, inside = (before, after) if outside_before else (after, before)
        score = outside - inside
        if score > best_score and inside < 0.6 * outside:
            best, best_score = i, score
    return best if best_score >= 8 else None


def locate(frames: list[np.ndarray], faces_per_frame: list[list[tuple]]) -> Rect | None:
    if not frames:
        return None
    height, width = frames[0].shape
    face = persistent_face(faces_per_frame, len(frames))
    if face is None:
        return None
    fx, fy, fw, fh = face
    if fh > MAX_FACE_HEIGHT * height:
        log.info("Face fills the frame; treating as a full-screen camera, not an overlay")
        return None

    left, top, right, bottom = _estimate(face, width, height)
    stack = np.stack(frames).astype(np.float32)
    motion = np.abs(np.diff(stack, axis=0)).mean(axis=0) if len(frames) > 1 else np.zeros_like(stack[0])
    gameplay_motion = float(np.median(motion))

    def settle(found, estimate, profile, edge):
        """A detected border wins. Otherwise extend to the frame edge if everything between
        the estimate and the edge is still (cam-like), or if the estimate nearly touches it."""
        if found is not None:
            return found
        lo, hi = sorted((int(estimate), edge))
        between = profile[lo:hi]
        if abs(estimate - edge) < SNAP_MARGIN * len(profile) or (
            between.size and between.mean() < 0.6 * gameplay_motion
        ):
            return edge
        return estimate

    # Left/right borders: motion per column, over rows we're confident are inside the cam.
    r0, r1 = max(0, int(fy - 0.3 * fh)), min(height, int(fy + 1.3 * fh))
    cols = np.median(motion[r0:r1], axis=0)
    span_w = right - left
    found = _find_step(cols, int(left - 0.5 * span_w), int(fx - 0.1 * fw), outside_before=True)
    left = settle(found, left, cols, 0)
    found = _find_step(cols, int(fx + 1.1 * fw), int(right + 0.5 * span_w) + 1, outside_before=False)
    right = settle(found, right, cols, width)

    # Top/bottom borders: motion per row, over columns inside the (refined) cam.
    inset = 0.1 * (right - left)
    rows = np.median(motion[:, int(left + inset) : max(int(left + inset) + 1, int(right - inset))], axis=1)
    span_h = bottom - top
    found = _find_step(rows, int(top - 0.5 * span_h), int(fy - 0.1 * fh), outside_before=True)
    top = settle(found, top, rows, 0)
    found = _find_step(rows, int(fy + 1.2 * fh), int(bottom + 0.5 * span_h) + 1, outside_before=False)
    bottom = settle(found, bottom, rows, height)

    if not (left <= fx and top <= fy and right >= fx + fw and bottom >= fy + fh):
        return None
    if (right - left) * (bottom - top) > 0.5 * width * height:
        return None  # too big to be an overlay
    return Rect(
        round(left / width, 4), round(top / height, 4),
        round((right - left) / width, 4), round((bottom - top) / height, 4),
    )


def save_preview(video: Path, rect: Rect | None, dst: Path, at: float = 0.5) -> Path:
    """Write a mid-clip frame with the facecam box drawn on it, for checking detection."""
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) * at))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Could not read a frame from {video}")
    if rect is not None:
        h, w = frame.shape[:2]
        p1 = (int(rect.x * w), int(rect.y * h))
        p2 = (int((rect.x + rect.w) * w) - 1, int((rect.y + rect.h) * h) - 1)
        cv2.rectangle(frame, p1, p2, (0, 255, 0), max(2, w // 300))
    cv2.imwrite(str(dst), frame)
    return dst


def detect(video: Path, samples: int = 16) -> Rect | None:
    """Return the facecam region of `video` as frame fractions, or None if there isn't one."""
    frames = sample_frames(video, samples)
    if len(frames) < 3:
        return None
    rect = locate(frames, [find_faces(f) for f in frames])
    log.info("Facecam detection for %s: %s", video.name, rect or "none found")
    return rect
