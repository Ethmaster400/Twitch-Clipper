from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .render import LAYOUTS, Rect


@dataclass
class Streamer:
    login: str
    permission: str
    extra_hashtags: list[str] = field(default_factory=list)
    layout: str | None = None          # overrides render.layout for this streamer (auto/blur/crop/split)
    facecam: Rect | None = None        # where their webcam sits in the 16:9 frame
    gameplay: Rect | None = None       # optional gameplay region for the split layout


@dataclass
class Config:
    raw: dict
    streamers: list[Streamer]
    data_dir: Path

    def section(self, name: str) -> dict:
        return self.raw.get(name) or {}

    def platform(self, name: str) -> dict:
        return (self.raw.get("platforms") or {}).get(name) or {}


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable {name} (see .env.example)")
    return value


def load(path: str | Path = "config.yaml") -> Config:
    load_dotenv()
    raw = yaml.safe_load(Path(path).read_text()) or {}

    streamers = []
    for entry in raw.get("streamers") or []:
        if not entry.get("permission"):
            raise ValueError(
                f"Streamer {entry.get('login')!r} has no `permission` recorded; "
                "only add streamers who agreed to have their clips reposted."
            )
        layout = entry.get("layout")
        if layout and layout not in LAYOUTS + ("auto",):
            raise ValueError(f"Streamer {entry['login']!r}: unknown layout {layout!r}")
        streamers.append(
            Streamer(
                login=entry["login"].lower(),
                permission=entry["permission"],
                extra_hashtags=entry.get("extra_hashtags") or [],
                layout=layout,
                facecam=Rect.parse(entry["facecam"]) if entry.get("facecam") else None,
                gameplay=Rect.parse(entry["gameplay"]) if entry.get("gameplay") else None,
            )
        )

    data_dir = Path(raw.get("data_dir", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(raw=raw, streamers=streamers, data_dir=data_dir)
