"""Turn a 16:9 clip into a 9:16 vertical video with ffmpeg."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

LAYOUTS = ("blur", "crop", "split")


@dataclass
class Rect:
    """A region of the source frame, as fractions (0-1) of its width/height."""
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def parse(cls, value) -> "Rect":
        if isinstance(value, Rect):
            return value
        if isinstance(value, str):
            value = [float(v) for v in value.split(",")]
        if isinstance(value, dict):
            value = [value["x"], value["y"], value["w"], value["h"]]
        rect = cls(*map(float, value))
        if not (0 <= rect.x < 1 and 0 <= rect.y < 1 and 0 < rect.w <= 1 and 0 < rect.h <= 1
                and rect.x + rect.w <= 1.0001 and rect.y + rect.h <= 1.0001):
            raise ValueError(f"Region {value!r} must be fractions inside the frame (x, y, w, h)")
        return rect

    def crop(self) -> str:
        return f"crop=w=iw*{self.w}:h=ih*{self.h}:x=iw*{self.x}:y=ih*{self.y}"


FULL_FRAME = Rect(0, 0, 1, 1)


def _filter_path(path: Path) -> str:
    # Escape for use inside an ffmpeg filtergraph option value.
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _fill(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"


def split_heights(height: int, facecam_ratio: float) -> tuple[int, int]:
    top = int(height * facecam_ratio) // 2 * 2
    return top, height - top


def build_filter(
    layout: str,
    width: int,
    height: int,
    subtitles: Path | None = None,
    *,
    facecam: Rect | None = None,
    gameplay: Rect | None = None,
    facecam_ratio: float = 0.35,
) -> str:
    if layout == "blur":
        graph = (
            f"[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]{_fill(width, height)},gblur=sigma=30,eq=brightness=-0.08[bg];"
            f"[fgsrc]scale={width}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    elif layout == "crop":
        graph = f"[0:v]{_fill(width, height)}"
    elif layout == "split":
        if facecam is None:
            raise ValueError("The split layout needs a facecam region")
        top, bottom = split_heights(height, facecam_ratio)
        graph = (
            f"[0:v]split=2[camsrc][gamesrc];"
            f"[camsrc]{facecam.crop()},{_fill(width, top)}[cam];"
            f"[gamesrc]{(gameplay or FULL_FRAME).crop()},{_fill(width, bottom)}[game];"
            f"[cam][game]vstack=inputs=2"
        )
    else:
        raise ValueError(f"Unknown layout {layout!r} (use one of {', '.join(LAYOUTS)})")

    graph += ",setsar=1"
    if subtitles is not None:
        graph += f",ass='{_filter_path(subtitles)}'"
    return graph + "[out]"


def render_vertical(
    src: Path,
    dst: Path,
    *,
    layout: str = "blur",
    width: int = 1080,
    height: int = 1920,
    subtitles: Path | None = None,
    facecam: Rect | None = None,
    gameplay: Rect | None = None,
    facecam_ratio: float = 0.35,
) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    graph = build_filter(
        layout, width, height, subtitles, facecam=facecam, gameplay=gameplay, facecam_ratio=facecam_ratio
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-filter_complex", graph,
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True)
    return dst


def snapshot(src: Path, dst: Path, at: float = 1.0) -> Path:
    """Save one frame, to help work out a streamer's facecam region."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(at), "-i", str(src), "-frames:v", "1", str(dst)],
        check=True,
    )
    return dst
