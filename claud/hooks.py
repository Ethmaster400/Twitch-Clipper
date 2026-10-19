"""A short all-caps hook line shown at the top of the video for the first few seconds.

Claude writes it from the transcript when Anthropic credentials are available; otherwise
a keyword fallback picks one. Idea and fallback phrases adapted from
coltonalmeida/twitch-clipper (MIT, Copyright (c) 2026 Colton Almeida).
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("claud")

DEFAULT_MODEL = "claude-opus-5-5"
MIN_WORDS, MAX_WORDS = 3, 8

PROMPT = (
    "You write the hook text overlay for a short vertical video of a Twitch clip. "
    "Write one punchy hook of 4 to 8 words that makes viewers want to keep watching. "
    "Base it on what actually happens; don't invent events. "
    "Reply with only the hook: no quotes, emojis, hashtags or explanation.\n\n"
    "Clip title: {title}\nStreamer: {streamer}\n\nTranscript:\n{transcript}"
)

KEYWORD_HOOKS = (
    (("leak", "leaked", "showed", "screen", "address", "discord"), "HE DID NOT MEAN TO SHOW THAT"),
    (("caught", "exposed", "noticed", "accident", "accidentally"), "CHAT CAUGHT IT IMMEDIATELY"),
    (("awkward", "weird", "silence", "embarrassing", "cringe"), "THIS TURNED AWKWARD FAST"),
    (("lol", "lmao", "laugh", "laughing", "hilarious", "funny", "joke"), "HE DID NOT JUST SAY THAT"),
    (("reaction", "react", "oh my god", "omg", "no way", "insane"), "THIS REACTION WAS INSANE"),
    (("clutch", "1v", "ace", "win", "won"), "WATCH THIS CLUTCH"),
    (("wait", "what", "huh", "unexpected", "crazy", "nobody", "why"), "NOBODY EXPECTED THIS"),
)


def clean(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", text.upper())
    if len(words) < MIN_WORDS:
        return ""
    return " ".join(words[:MAX_WORDS])


def keyword_hook(text: str) -> str:
    lowered = f" {text.lower()} "
    for keywords, hook in KEYWORD_HOOKS:
        if any(f" {k} " in lowered or (" " in k and k in lowered) for k in keywords):
            return hook
    return "NOBODY EXPECTED THIS"


def claude_hook(transcript: str, title: str, streamer: str, model: str = DEFAULT_MODEL) -> str:
    import anthropic

    client = anthropic.Anthropic(max_retries=2, timeout=60.0)
    response = client.beta.messages.create(
        model=model,
        max_tokens=2000,
        output_config={"effort": "low"},
        # On a safety decline, let the API retry on a suitable fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": PROMPT.format(title=title, streamer=streamer, transcript=transcript[:2000] or "(no speech)"),
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write a hook")
    text = "".join(block.text for block in response.content if block.type == "text")
    hook = clean(text)
    if not hook:
        raise RuntimeError(f"Unusable hook from Claude: {text!r}")
    return hook


def generate(transcript: str, title: str, streamer: str, cfg: dict | None = None) -> str:
    cfg = cfg or {}
    if cfg.get("use_claude", True):
        try:
            return claude_hook(transcript, title, streamer, cfg.get("model", DEFAULT_MODEL))
        except Exception as e:  # missing key, network, refusal: never block a clip on the hook
            log.warning("Claude hook failed (%s); using keyword fallback", e)
    return keyword_hook(f"{title} {transcript}")
