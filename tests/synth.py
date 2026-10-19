"""Synthetic stream videos for facecam tests: moving 'gameplay' noise plus an optional webcam overlay."""
import subprocess

import numpy as np


def face_image():
    from skimage import data
    return data.astronaut()[:384]  # 512x384 RGB with one clear face


def resize(img, w, h):
    ys = (np.arange(h) * img.shape[0] / h).astype(int)
    xs = (np.arange(w) * img.shape[1] / w).astype(int)
    return img[ys][:, xs]


def make_stream(path, cam=None, size=(1280, 720), seconds=3, fps=10, seed=0, fullscreen_face=False):
    """cam: (x, y, w, h) in pixels where the face overlay goes, or None for gameplay only."""
    rng = np.random.default_rng(seed)
    w, h = size
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(path)],
        stdin=subprocess.PIPE,
    )
    face = face_image()
    for _ in range(seconds * fps):
        blocks = rng.integers(0, 256, (h // 16 + 1, w // 16 + 1, 3), dtype=np.uint8)
        frame = np.repeat(np.repeat(blocks, 16, 0), 16, 1)[:h, :w].copy()
        if fullscreen_face:
            frame = resize(face, w, h).copy()
        if cam:
            x, y, cw, ch = cam
            overlay = resize(face, cw, ch).astype(np.int16) + rng.integers(-3, 4, (ch, cw, 1))
            frame[y : y + ch, x : x + cw] = np.clip(overlay, 0, 255).astype(np.uint8)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    return path
