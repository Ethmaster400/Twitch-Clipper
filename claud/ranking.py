"""Rank candidate clips by more than raw views.

Scoring adapted from coltonalmeida/twitch-clipper (MIT, Copyright (c) 2026 Colton Almeida):
each signal is normalised to 0-1 across the candidate pool, then weighted, so a clip
taking off right now can beat an older clip with more total views.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .twitch import Clip

DEFAULT_WEIGHTS = {
    "velocity": 0.30,   # views per hour since the clip was made
    "views": 0.25,      # total views (log scale)
    "recency": 0.15,    # newer is better, halving every `recency_half_life_hours`
    "duration": 0.15,   # 15-60s is the Shorts/TikTok sweet spot
    "title": 0.15,      # energetic titles tend to be better moments
}
RECENCY_HALF_LIFE_HOURS = 48.0

ENERGETIC_WORDS = (
    "insane", "crazy", "clutch", "no way", "omg", "wtf", "unreal", "wild", "rage",
    "destroyed", "best", "shocked", "screaming", "roasted", "amazing",
)
BORING_TITLES = ("clip", "highlight", "lol", "twitch", "untitled")


def _age_hours(clip: Clip, now: datetime) -> float:
    try:
        created = datetime.fromisoformat(clip.created_at.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return max((now - created).total_seconds() / 3600, 0.0)


def velocity(clip: Clip, now: datetime) -> float:
    age = _age_hours(clip, now)
    return 0.0 if math.isinf(age) else clip.views / max(age, 1.0)


def duration_score(seconds: float) -> float:
    if 15 <= seconds <= 60:
        return 1.0
    if seconds < 15:
        return max(0.0, (seconds - 5) / 10)
    return max(0.0, 1 - (seconds - 60) / 30)


def title_score(title: str) -> float:
    text = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", title.lower())).strip()
    if not text:
        return 0.25
    score = 0.55
    if any(word in text for word in ENERGETIC_WORDS):
        score += 0.30
    if "!" in title or "?" in title:
        score += 0.10
    if len(text.split()) >= 4:
        score += 0.05
    if text.split()[0] in BORING_TITLES and len(text.split()) <= 2:
        score -= 0.20
    return min(max(score, 0.0), 1.0)


def rank(clips: list[Clip], cfg: dict | None = None, now: datetime | None = None) -> list[tuple[float, Clip]]:
    """Return (score, clip) pairs, best first."""
    cfg = cfg or {}
    weights = {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}
    half_life = cfg.get("recency_half_life_hours", RECENCY_HALF_LIFE_HOURS)
    now = now or datetime.now(timezone.utc)

    max_views = max((c.views for c in clips), default=0)
    max_velocity = max((velocity(c, now) for c in clips), default=0.0)

    def log_norm(value: float, top: float) -> float:
        return math.log1p(value) / math.log1p(top) if top > 0 else 0.0

    scored = []
    for clip in clips:
        age = _age_hours(clip, now)
        parts = {
            "velocity": log_norm(velocity(clip, now), max_velocity),
            "views": log_norm(clip.views, max_views),
            "recency": 0.0 if math.isinf(age) else math.exp(-age / half_life),
            "duration": duration_score(clip.duration),
            "title": title_score(clip.title),
        }
        scored.append((sum(weights[k] * parts[k] for k in parts), clip))
    return sorted(scored, key=lambda pair: (pair[0], pair[1].views), reverse=True)
