"""'Manual' destination: put finished videos in a folder for you to upload yourself.

Files are named after the TikTok caption, because TikTok Studio pre-fills the
description from the file name. Each video also gets a .txt next to it with the full
caption and the YouTube title and description, ready to paste.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..metadata import PostMeta, tiktok_caption

MAX_NAME = 150  # keeps full paths well under Windows' 260-character limit


def safe_filename(text: str, max_len: int = MAX_NAME) -> str:
    """Turn a caption into a valid file name on Windows, macOS and Linux."""
    text = text.replace("|", "-").replace(":", " -").replace("/", "-").replace("\\", "-")
    text = re.sub(r'[<>"?*\x00-\x1f]', "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    text = text.rstrip(". ")  # Windows drops trailing dots and spaces
    return text or "clip"


def upload(video: Path, meta: PostMeta, cfg: dict) -> str:
    folder = Path(cfg.get("folder", "data/ready"))
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_filename(tiktok_caption(meta))
    target, n = folder / f"{name}.mp4", 2
    while target.exists():
        target, n = folder / f"{name} ({n}).mp4", n + 1
    shutil.copy2(video, target)
    target.with_suffix(".txt").write_text(
        "TIKTOK CAPTION\n"
        f"{tiktok_caption(meta)}\n\n"
        "YOUTUBE TITLE\n"
        f"{meta.title}\n\n"
        "YOUTUBE DESCRIPTION\n"
        f"{meta.description}\n",
        encoding="utf-8",
    )
    return str(target)
