"""Twitch Helix API: find popular clips and download them."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HELIX = "https://api.twitch.tv/helix"


@dataclass
class Clip:
    id: str
    streamer: str
    title: str
    url: str
    views: int
    duration: float
    game_id: str
    game_name: str = ""
    created_at: str = ""


class Twitch:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_expiry = 0.0
        self._game_cache: dict[str, str] = {}

    def _auth_headers(self) -> dict:
        if not self._token or time.time() > self._token_expiry - 60:
            r = requests.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=30,
            )
            r.raise_for_status()
            body = r.json()
            self._token = body["access_token"]
            self._token_expiry = time.time() + body["expires_in"]
        return {"Client-Id": self.client_id, "Authorization": f"Bearer {self._token}"}

    def _get(self, path: str, params) -> dict:
        r = requests.get(f"{HELIX}{path}", params=params, headers=self._auth_headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def user_id(self, login: str) -> str:
        data = self._get("/users", {"login": login})["data"]
        if not data:
            raise ValueError(f"Twitch user {login!r} not found")
        return data[0]["id"]

    def game_names(self, game_ids: set[str]) -> dict[str, str]:
        missing = [g for g in game_ids if g and g not in self._game_cache]
        for i in range(0, len(missing), 100):
            batch = missing[i : i + 100]
            for game in self._get("/games", [("id", g) for g in batch])["data"]:
                self._game_cache[game["id"]] = game["name"]
        return {g: self._game_cache.get(g, "") for g in game_ids}

    def top_clips(self, login: str, lookback_hours: int) -> list[Clip]:
        now = datetime.now(timezone.utc)
        params = {
            "broadcaster_id": self.user_id(login),
            "started_at": (now - timedelta(hours=lookback_hours)).isoformat(timespec="seconds"),
            "ended_at": now.isoformat(timespec="seconds"),
            "first": 100,
        }
        clips = [
            Clip(
                id=c["id"],
                streamer=c["broadcaster_name"],
                title=c["title"].strip(),
                url=c["url"],
                views=c["view_count"],
                duration=c["duration"],
                game_id=c["game_id"],
                created_at=c["created_at"],
            )
            for c in self._get("/clips", params)["data"]
        ]
        names = self.game_names({c.game_id for c in clips})
        for c in clips:
            c.game_name = names.get(c.game_id, "")
        return clips


def select_clips(clips: list[Clip], *, min_views: int, max_duration_s: float) -> list[Clip]:
    """Filter by view count and length, most viewed first."""
    keep = [c for c in clips if c.views >= min_views and c.duration <= max_duration_s]
    return sorted(keep, key=lambda c: c.views, reverse=True)


def download(clip: Clip, out_dir: Path) -> Path:
    """Download the clip MP4 with yt-dlp (Helix does not expose clip media URLs)."""
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{clip.id}.mp4"
    if target.exists():
        return target
    opts = {
        "outtmpl": str(target),
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([clip.url])
    return target
