"""Skip clips whose titles suggest content that gets accounts flagged.

Default term list adapted from coltonalmeida/twitch-clipper (MIT, Copyright (c) 2026 Colton Almeida).
"""
from __future__ import annotations

import re

BLOCKED_TERMS = (
    "nsfw", "nude", "nudity", "naked", "porn", "xxx", "sex tape", "onlyfans",
    "leaked nudes", "doxxed", "dox", "swat", "swatted", "suicide", "self harm", "kill myself",
)


def blocked_term(title: str, cfg: dict | None = None) -> str | None:
    """The first blocked term found in the title (as whole words), or None if it's fine."""
    cfg = cfg or {}
    if cfg.get("enabled", True) is False:
        return None
    text = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", title.lower())) + " "
    for term in tuple(BLOCKED_TERMS) + tuple(t.lower() for t in cfg.get("extra_terms") or []):
        if f" {term} " in text:
            return term
    return None
