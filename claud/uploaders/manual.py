"""'Manual' destination: put finished videos in a folder for you to upload yourself.

Each video gets a .txt next to it with the TikTok caption and the YouTube title and
description, ready to paste (e.g. into TikTok Studio at tiktok.com/tiktokstudio).
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ..metadata import PostMeta, tiktok_caption


def upload(video: Path, meta: PostMeta, cfg: dict) -> str:
    folder = Path(cfg.get("folder", "data/ready"))
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d_%H%M}_{video.stem}"
    target = folder / f"{stem}.mp4"
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
