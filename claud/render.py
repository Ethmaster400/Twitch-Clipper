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


def _blur_fit(width: int, height: int, src: str, out: str) -> str:
    """Whole frame scaled to fit, over a blurred, darkened copy filling the area."""
    return (
        f"{src}split=2[{out}_b][{out}_f];"
        f"[{out}_b]{_fill(width, height)},gblur=sigma=30,eq=brightness=-0.08[{out}_bg];"
        f"[{out}_f]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[{out}_fg];"
        f"[{out}_bg][{out}_fg]overlay=(W-w)/2:(H-h)/2"
    )


def build_filter(
    layout: str,
    width: int,
    height: int,
    subtitles: Path | None = None,
    *,
    facecam: Rect | None = None,
    gameplay: Rect | None = None,
    facecam_ratio: float = 0.35,
    gameplay_mode: str = "crop",
    divider: bool = True,
) -> str:
    """gameplay_mode (split layout): "crop" zooms into a slice of the gameplay that fills its
    panel; "fit" shows the whole gameplay frame over a blurred copy (from streamclip).
    divider: a thin dark line between the facecam and gameplay panels."""
    if gameplay_mode not in ("crop", "fit"):
        raise ValueError(f"Unknown gameplay_mode {gameplay_mode!r} (use 'crop' or 'fit')")
    if layout == "blur":
        graph = _blur_fit(width, height, "[0:v]", "full")
    elif layout == "crop":
        graph = f"[0:v]{_fill(width, height)}"
    elif layout == "split":
        if facecam is None:
            raise ValueError("The split layout needs a facecam region")
        top, bottom = split_heights(height, facecam_ratio)
        game_src = f"[gamesrc]{(gameplay or FULL_FRAME).crop()},setsar=1,"
        if gameplay_mode == "fit":
            game = f"{game_src}null[gamecrop];" + _blur_fit(width, bottom, "[gamecrop]", "game") + "[game]"
        else:
            game = f"{game_src}{_fill(width, bottom)}[game]"
        graph = (
            f"[0:v]split=2[camsrc][gamesrc];"
            f"[camsrc]{facecam.crop()},{_fill(width, top)},setsar=1[cam];"
            f"{game};"
            f"[cam][game]vstack=inputs=2"
        )
        if divider:
            graph += f",drawbox=x=0:y={top - 3}:w=iw:h=6:color=black@0.85:t=fill"
    else:
        raise ValueError(f"Unknown layout {layout!r} (use one of {', '.join(LAYOUTS)})")

    graph += ",setsar=1"
    if subtitles is not None:
        graph += f",ass='{_filter_path(subtitles)}'"
    return graph + "[out]"


LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"  # about the loudness TikTok / Shorts play at
MAX_FPS = 60

_nvenc: bool | None = None


def nvenc_available() -> bool:
    """True if ffmpeg can encode with an NVIDIA GPU (h264_nvenc); checked once."""
    global _nvenc
    if _nvenc is None:
        test = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True,
        )
        _nvenc = test.returncode == 0
    return _nvenc


def video_encoder(encoder: str = "auto") -> list[str]:
    """encoder: auto (NVIDIA GPU if available, else CPU), nvenc or cpu."""
    if encoder == "nvenc" or (encoder == "auto" and nvenc_available()):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]


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
    gameplay_mode: str = "crop",
    divider: bool = True,
    loudnorm: bool = True,
    encoder: str = "auto",
) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    graph = build_filter(
        layout, width, height, subtitles, facecam=facecam, gameplay=gameplay,
        facecam_ratio=facecam_ratio, gameplay_mode=gameplay_mode, divider=divider,
    )
    # Keep the clip's own frame rate (Twitch clips are often 60 fps), capped at MAX_FPS.
    graph = graph.removesuffix("[out]") + f",fps=fps='min(source_fps,{MAX_FPS})'[out]"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-filter_complex", graph,
        "-map", "[out]", "-map", "0:a?",
        *video_encoder(encoder), "-pix_fmt", "yuv420p",
        *(["-af", LOUDNORM] if loudnorm else []),
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
