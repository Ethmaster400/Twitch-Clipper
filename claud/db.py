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


class DB:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def upsert_clip(self, clip) -> None:
        self.conn.execute(
            "INSERT INTO clips (id, streamer, title, url, views) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET views = excluded.views",
            (clip.id, clip.streamer, clip.title, clip.url, clip.views),
        )
        self.conn.commit()

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
