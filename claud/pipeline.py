"""End-to-end run: find clips -> download -> caption -> render -> upload."""
from __future__ import annotations

import logging
from pathlib import Path

from . import captions, content_filter, hooks, metadata, ranking, render, twitch
from .config import Config, Streamer, env
from .render import Rect
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
    pool = []
    for streamer in cfg.streamers:
        try:
            clips = tw.top_clips(streamer.login, sel.get("lookback_hours", 48))
        except Exception as e:
            log.error("Fetching clips for %s failed: %s", streamer.login, e)
            continue
        for clip in twitch.select_clips(
            clips, min_views=sel.get("min_views", 0), max_duration_s=sel.get("max_duration_s", 60)
        ):
            term = content_filter.blocked_term(clip.title, cfg.section("content_filter"))
            if term:
                log.info("Skipping %r: title matches blocked term %r", clip.title, term)
                continue
            pool.append(clip)

    found = []
    for score, clip in ranking.rank(pool, cfg.section("ranking")):
        todo = [p for p in platforms if db.needs_post(clip.id, p)]
        if todo:
            log.debug("Candidate %.3f %s %r", score, clip.streamer, clip.title)
            found.append((clip, todo))
    return found[: sel.get("max_posts_per_run", 3)]


def resolve_layout(rcfg: dict, streamer: Streamer | None, src: Path | None = None,
                   detect=None) -> tuple[str, Rect | None]:
    """Pick the layout and facecam region for one clip.

    Per-streamer layout wins over render.layout. For `auto` and `split`, a facecam set in the
    config is used as-is; otherwise it is detected from the clip. No facecam -> blur (fit + blurred background).
    """
    layout = (streamer and streamer.layout) or rcfg.get("layout", "auto")
    if layout not in ("auto", "split"):
        return layout, None
    if streamer and streamer.facecam:
        return "split", streamer.facecam
    facecam = None
    if src is not None and rcfg.get("detect_facecam", True):
        try:
            facecam = (detect or detect_facecam)(src)
        except Exception as e:
            log.warning("Facecam detection failed for %s: %s", src.name, e)
    if facecam is None:
        log.info("No facecam for %s; using blur", streamer.login if streamer else src)
        return "blur", None
    return "split", facecam


def detect_facecam(src: Path) -> Rect | None:
    from . import facecam
    return facecam.detect(src)


def prepare_video(cfg: Config, clip: Clip, raw_dir: Path, out_dir: Path, streamer: Streamer | None = None) -> Path:
    rcfg = cfg.section("render")
    width, height = rcfg.get("width", 1080), rcfg.get("height", 1920)
    out = out_dir / f"{clip.id}.mp4"
    if out.exists():
        return out

    facecam_ratio = rcfg.get("facecam_height", 0.35)
    src = twitch.download(clip, raw_dir)
    layout, facecam = resolve_layout(rcfg, streamer, src)
    words = (
        captions.transcribe(src, rcfg.get("whisper_model", "small"), rcfg.get("whisper_device", "auto"))
        if rcfg.get("captions", True) else []
    )
    chunks = captions.group_words(words, rcfg.get("words_per_caption", 3)) if words else []

    hcfg = cfg.section("hook")
    hook = None
    if hcfg.get("enabled", True):
        hook = hooks.generate(" ".join(w.text for w in words), clip.title, clip.streamer, hcfg)
        log.info("Hook for %s: %s", clip.id, hook)

    subs = None
    if chunks or hook:
        # In the split layout, captions sit on the seam between facecam and gameplay and the
        # hook goes just below them, so neither covers the streamer's face. Otherwise the hook
        # sits at the top, over the blurred background.
        center_y = facecam_ratio if layout == "split" else 0.7
        hook_top = facecam_ratio + 0.045 if layout == "split" else 0.07
        subs = captions.write_ass(
            chunks, raw_dir / f"{clip.id}.ass", width, height, center_y,
            hook=hook, hook_seconds=hcfg.get("seconds", 3.0), hook_top=hook_top,
        )
    return render.render_vertical(
        src, out, layout=layout, width=width, height=height, subtitles=subs,
        facecam=facecam,
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
