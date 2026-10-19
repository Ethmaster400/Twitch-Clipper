"""End-to-end run: find clips -> download -> caption -> render -> upload."""
from __future__ import annotations

import logging
from pathlib import Path

from . import captions, metadata, render, twitch
from .config import Config, Streamer, env
from .db import DB
from .twitch import Clip

log = logging.getLogger("claud")

PLATFORMS = ("youtube", "tiktok")


def _uploader(name: str):
    if name == "youtube":
        from .uploaders import youtube
        return youtube.upload
    from .uploaders import tiktok
    return tiktok.upload


def enabled_platforms(cfg: Config) -> list[str]:
    return [p for p in PLATFORMS if cfg.platform(p).get("enabled")]


def find_candidates(cfg: Config, tw: twitch.Twitch, db: DB, platforms: list[str]) -> list[tuple[Clip, list[str]]]:
    sel = cfg.section("selection")
    found = []
    for streamer in cfg.streamers:
        try:
            clips = tw.top_clips(streamer.login, sel.get("lookback_hours", 48))
        except Exception as e:
            log.error("Fetching clips for %s failed: %s", streamer.login, e)
            continue
        for clip in twitch.select_clips(
            clips, min_views=sel.get("min_views", 0), max_duration_s=sel.get("max_duration_s", 60)
        ):
            todo = [p for p in platforms if db.needs_post(clip.id, p)]
            if todo:
                found.append((clip, todo))
    found.sort(key=lambda item: item[0].views, reverse=True)
    return found[: sel.get("max_posts_per_run", 3)]


def resolve_layout(rcfg: dict, streamer: Streamer | None) -> str:
    """Per-streamer layout wins; split falls back to blur if we don't know where the facecam is."""
    layout = (streamer and streamer.layout) or rcfg.get("layout", "blur")
    if layout == "split" and not (streamer and streamer.facecam):
        log.warning("Split layout needs a facecam region for %s; using blur", streamer and streamer.login)
        return "blur"
    return layout


def prepare_video(cfg: Config, clip: Clip, raw_dir: Path, out_dir: Path, streamer: Streamer | None = None) -> Path:
    rcfg = cfg.section("render")
    width, height = rcfg.get("width", 1080), rcfg.get("height", 1920)
    out = out_dir / f"{clip.id}.mp4"
    if out.exists():
        return out

    layout = resolve_layout(rcfg, streamer)
    facecam_ratio = rcfg.get("facecam_height", 0.35)
    src = twitch.download(clip, raw_dir)
    subs = None
    if rcfg.get("captions", True):
        words = captions.transcribe(src, rcfg.get("whisper_model", "small"))
        if words:
            chunks = captions.group_words(words, rcfg.get("words_per_caption", 3))
            # In the split layout, captions sit on the seam between facecam and gameplay.
            center_y = facecam_ratio if layout == "split" else 0.7
            subs = captions.write_ass(chunks, raw_dir / f"{clip.id}.ass", width, height, center_y)
    return render.render_vertical(
        src, out, layout=layout, width=width, height=height, subtitles=subs,
        facecam=streamer.facecam if streamer else None,
        gameplay=streamer.gameplay if streamer else None,
        facecam_ratio=facecam_ratio,
    )


def run(cfg: Config, *, dry_run: bool = False) -> None:
    platforms = enabled_platforms(cfg)
    if not platforms:
        log.warning("No platforms enabled in config")
    db = DB(cfg.data_dir / "claud.db")
    tw = twitch.Twitch(env("TWITCH_CLIENT_ID"), env("TWITCH_CLIENT_SECRET"))
    streamers = {s.login: s for s in cfg.streamers}

    candidates = find_candidates(cfg, tw, db, platforms)
    log.info("%d clip(s) to post", len(candidates))

    for clip, todo in candidates:
        log.info("[%s] %r (%d views) -> %s", clip.streamer, clip.title, clip.views, ", ".join(todo))
        db.upsert_clip(clip)
        streamer = streamers.get(clip.streamer.lower())
        try:
            video = prepare_video(cfg, clip, cfg.data_dir / "raw", cfg.data_dir / "out", streamer)
        except Exception as e:
            log.exception("Preparing %s failed", clip.id)
            for p in todo:
                db.record_post(clip.id, p, error=f"render: {e}")
            continue
        db.set_video_path(clip.id, str(video))

        meta = metadata.build(clip, cfg.section("metadata"), streamer.extra_hashtags if streamer else None)
        if dry_run:
            log.info("Dry run: rendered %s, title %r", video, meta.title)
            continue

        for p in todo:
            try:
                remote_id = _uploader(p)(video, meta, cfg.platform(p))
                db.record_post(clip.id, p, remote_id=remote_id)
                log.info("Posted %s to %s (%s)", clip.id, p, remote_id)
            except Exception as e:
                log.exception("Upload of %s to %s failed", clip.id, p)
                db.record_post(clip.id, p, error=str(e))
