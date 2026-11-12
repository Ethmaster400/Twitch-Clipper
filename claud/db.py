"""SQLite bookkeeping so a clip is never posted twice to the same platform."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    streamer TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    views INTEGER NOT NULL,
    video_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS posts (
    clip_id TEXT NOT NULL REFERENCES clips(id),
    platform TEXT NOT NULL,
    status TEXT NOT NULL,          -- posted / failed
    remote_id TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (clip_id, platform)
);
"""

MAX_ATTEMPTS = 3

# Where in the stream each clip is, for same-moment checks. Added after the first release,
# so they're added to existing databases on open.
MOMENT_COLUMNS = {"clip_created_at": "TEXT", "video_id": "TEXT", "vod_offset": "INTEGER"}


class DB:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(clips)")}
        for name, kind in MOMENT_COLUMNS.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE clips ADD COLUMN {name} {kind}")
        self.conn.commit()

    def upsert_clip(self, clip) -> None:
        self.conn.execute(
            "INSERT INTO clips (id, streamer, title, url, views, clip_created_at, video_id, vod_offset) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET views = excluded.views, "
            "clip_created_at = excluded.clip_created_at, video_id = excluded.video_id, "
            "vod_offset = excluded.vod_offset",
            (clip.id, clip.streamer, clip.title, clip.url, clip.views,
             clip.created_at, clip.video_id, clip.vod_offset),
        )
        self.conn.commit()

    def remember_moment(self, clip) -> None:
        """Fill in where a clip we already know about sits in the stream (older rows lack it)."""
        self.conn.execute(
            "UPDATE clips SET clip_created_at = ?, video_id = ?, vod_offset = ? WHERE id = ?",
            (clip.created_at, clip.video_id, clip.vod_offset, clip.id),
        )
        self.conn.commit()

    def posted_clips(self) -> list:
        """Clips posted at least once, with what's needed for same-moment checks."""
        from .twitch import Clip

        rows = self.conn.execute(
            "SELECT * FROM clips c WHERE EXISTS "
            "(SELECT 1 FROM posts p WHERE p.clip_id = c.id AND p.status = 'posted')"
        ).fetchall()
        return [
            Clip(id=r["id"], streamer=r["streamer"], title=r["title"], url=r["url"], views=r["views"],
                 duration=0, game_id="", created_at=r["clip_created_at"] or "",
                 video_id=r["video_id"] or "", vod_offset=r["vod_offset"])
            for r in rows
        ]

    def set_video_path(self, clip_id: str, path: str) -> None:
        self.conn.execute("UPDATE clips SET video_path = ? WHERE id = ?", (path, clip_id))
        self.conn.commit()

    def needs_post(self, clip_id: str, platform: str) -> bool:
        row = self.conn.execute(
            "SELECT status, attempts FROM posts WHERE clip_id = ? AND platform = ?",
            (clip_id, platform),
        ).fetchone()
        if row is None:
            return True
        return row["status"] == "failed" and row["attempts"] < MAX_ATTEMPTS

    def record_post(self, clip_id: str, platform: str, *, remote_id=None, error=None) -> None:
        status = "failed" if error else "posted"
        self.conn.execute(
            "INSERT INTO posts (clip_id, platform, status, remote_id, error) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(clip_id, platform) DO UPDATE SET status = excluded.status, "
            "remote_id = excluded.remote_id, error = excluded.error, "
            "attempts = posts.attempts + 1, updated_at = CURRENT_TIMESTAMP",
            (clip_id, platform, status, remote_id, error),
        )
        self.conn.commit()

    def reset_failed(self) -> int:
        """Forget failed attempts so those clips are tried again; returns how many."""
        count = self.conn.execute("DELETE FROM posts WHERE status = 'failed'").rowcount
        self.conn.commit()
        return count

    def history(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT c.streamer, c.title, c.views, p.platform, p.status, p.remote_id, p.error, p.updated_at "
            "FROM posts p JOIN clips c ON c.id = p.clip_id ORDER BY p.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
