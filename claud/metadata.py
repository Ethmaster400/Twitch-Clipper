"""Titles, descriptions and hashtags generated from clip info."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .twitch import Clip

YOUTUBE_TITLE_MAX = 100
TIKTOK_CAPTION_MAX = 2200


@dataclass
class PostMeta:
    title: str
    description: str
    hashtags: list[str]
    tags: list[str]  # YouTube keyword tags, no '#'


def hashtagify(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    return "#" + "".join(w[:1].upper() + w[1:] for w in words) if words else ""


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for item in items:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build(clip: Clip, cfg: dict, extra_hashtags: list[str] | None = None) -> PostMeta:
    hashtags = _dedupe(
        [hashtagify(clip.streamer), hashtagify(clip.game_name)]
        + list(extra_hashtags or [])
        + list(cfg.get("base_hashtags") or [])
    )
    fields = {
        "title": clip.title or "Twitch clip",
        "streamer": clip.streamer,
        "game": clip.game_name,
        "url": clip.url,
        "hashtags": " ".join(hashtags),
    }
    title = cfg.get("title_template", "{title} | {streamer}").format(**fields)
    description = cfg.get("description_template", "{title}\n\n{hashtags}").format(**fields).strip()
    tags = _dedupe([clip.streamer, clip.game_name, "twitch", "shorts"] + [h.lstrip("#") for h in hashtags])
    return PostMeta(
        title=_truncate(title, YOUTUBE_TITLE_MAX),
        description=description,
        hashtags=hashtags,
        tags=[t for t in tags if t],
    )


def tiktok_caption(meta: PostMeta) -> str:
    return _truncate(f"{meta.title} {' '.join(meta.hashtags)}", TIKTOK_CAPTION_MAX)
