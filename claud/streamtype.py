"""Label a clip as gaming or IRL from its Twitch category, to pick how it's edited.

Gaming clips usually have a facecam overlay on top of gameplay; IRL clips (Just Chatting,
music, travel, ...) are the camera itself, full screen.
"""
from __future__ import annotations

GAMING, IRL = "gaming", "irl"

IRL_CATEGORIES = {
    "just chatting",
    "irl",
    "talk shows & podcasts",
    "music",
    "travel & outdoors",
    "food & drink",
    "special events",
    "pools, hot tubs, and beaches",
    "asmr",
    "art",
    "makers & crafting",
    "fitness & health",
    "beauty & body art",
}


def classify(category: str, extra_irl: list[str] | tuple[str, ...] = ()) -> str:
    """'irl' for talking/camera categories, 'gaming' for everything else (including unknown)."""
    name = (category or "").strip().lower()
    if name in IRL_CATEGORIES or name in {c.strip().lower() for c in extra_irl}:
        return IRL
    return GAMING
