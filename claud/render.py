"""Turn a 16:9 clip into a 9:16 vertical video with ffmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path


def _filter_path(path: Path) -> str:
    # Escape for use inside an ffmpeg filtergraph option value.
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def build_filter(layout: str, width: int, height: int, subtitles: Path | None = None) -> str:
    if layout == "blur":
        graph = (
            f"[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma=30,eq=brightness=-0.08[bg];"
            f"[fgsrc]scale={width}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    elif layout == "crop":
        graph = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    else:
        raise ValueError(f"Unknown layout {layout!r} (use 'blur' or 'crop')")

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
) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-filter_complex", build_filter(layout, width, height, subtitles),
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True)
    return dst
