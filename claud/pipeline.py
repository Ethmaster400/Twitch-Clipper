"""End-to-end run: find clips -> download -> caption -> render -> upload."""
from __future__ import annotations

import logging
from pathlib import Path

from . import budget, captions, content_filter, hooks, metadata, ranking, render, streamtype, twitch
from .config import Config, Streamer, env
from .render import Rect
from .db import DB
from .twitch import Clip

log = logging.getLogger("claud")

PLATFORMS = ("youtube", "tiktok", "uploadpost", "manual")


def _uploader(name: str):
    if name == "youtube":
        from .uploaders import youtube
        return youtube.upload
    if name == "manual":
        from .uploaders import manual
        return manual.upload
    if name == "uploadpost":
        from .uploaders import uploadpost
        return uploadpost.upload
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

    # Viewers often clip the same moment several times: keep only the best-ranked clip of
    # each moment, and never one whose moment was already posted on an earlier run.
    window = sel.get("same_moment_window_s", 90)
    for clip in pool:
        db.remember_moment(clip)
    taken = db.posted_clips() if window else []
    found = []
    for score, clip in ranking.rank(pool, cfg.section("ranking")):
        twin = next((t for t in taken if ranking.same_moment(clip, t, window)), None) if window else None
        if twin is not None:
            log.info("Skipping %r: same moment as %r", clip.title, twin.title)
            continue
        todo = [p for p in platforms if db.needs_post(clip.id, p)]
        if todo:
            log.debug("Candidate %.3f %s %r", score, clip.streamer, clip.title)
            found.append((clip, todo))
        taken.append(clip)
    return found[: sel.get("max_posts_per_run", 3)]


def resolve_layout(rcfg: dict, streamer: Streamer | None, src: Path | None = None,
                   detect=None, stream_type: str = streamtype.GAMING,
                   find_face=None) -> tuple[str, Rect | None]:
    """Pick the layout and the region it needs (facecam for split, crop window for face).

    A per-streamer layout wins. Otherwise the clip's stream type decides, via
    render.layout_by_type (default: gaming -> render.layout / auto, irl -> face).
    auto/split: facecam on top if one is set or detected, else blur.
    face: full-screen crop centred on the person, else blur.
    """
    by_type = {streamtype.GAMING: rcfg.get("layout", "auto"), streamtype.IRL: "face",
               **(rcfg.get("layout_by_type") or {})}
    layout = (streamer and streamer.layout) or by_type.get(stream_type, "auto")
    who = streamer.login if streamer else src
    if layout == "face":
        window = None
        if src is not None:
            try:
                window = (find_face or detect_face_window)(src)
            except Exception as e:
                log.warning("Face detection failed for %s: %s", getattr(src, "name", src), e)
        if window is None:
            log.info("No face to crop to for %s; using blur", who)
            return "blur", None
        return "face", window
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
        log.info("No facecam for %s; using blur", who)
        return "blur", None
    return "split", facecam


def detect_face_window(src: Path) -> Rect | None:
    from . import facecam
    return facecam.face_window(src)


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
    stype = streamtype.classify(clip.game_name, rcfg.get("irl_categories") or [])
    log.info("Stream type: %s (%s)", stype, clip.game_name or "unknown category")
    layout, region = resolve_layout(rcfg, streamer, src, stream_type=stype)
    words = (
        captions.transcribe(src, rcfg.get("whisper_model", "small"), rcfg.get("whisper_device", "auto"))
        if rcfg.get("captions", True) else []
    )
    chunks = (
        captions.group_words(words, rcfg.get("words_per_caption", 3), rcfg.get("caption_max_chars", 18))
        if words else []
    )

    hcfg = cfg.section("hook")
    hook = None
    if hcfg.get("enabled", True):
        hook = hooks.generate(" ".join(w.text for w in words), clip.title, clip.streamer, hcfg)
        log.info("Hook for %s: %s", clip.id, hook)

    subs = None
    if chunks or hook:
        # In the split layout, captions sit on the seam between facecam and gameplay and the
        # hook goes just below them, so neither covers the streamer's face. In blur/crop the
        # hook sits at the top, over the blurred background.
        center_y = facecam_ratio if layout == "split" else 0.7
        # face: the person fills the screen, so keep the hook off their head, above the captions
        hook_top = {"split": facecam_ratio + 0.045, "face": 0.58}.get(layout, 0.07)
        subs = captions.write_ass(
            chunks, raw_dir / f"{clip.id}.ass", width, height, center_y,
            hook=hook, hook_seconds=hcfg.get("seconds", 3.0), hook_top=hook_top,
            font=rcfg.get("caption_font", captions.DEFAULT_FONT),
        )
    return render.render_vertical(
        src, out, layout=layout, width=width, height=height, subtitles=subs,
        facecam=region if layout == "split" else None,
        window=region if layout == "face" else None,
        gameplay=streamer.gameplay if streamer else None,
        facecam_ratio=facecam_ratio,
        gameplay_mode=rcfg.get("gameplay_mode", "crop"),
        divider=rcfg.get("divider", True),
        loudnorm=rcfg.get("normalize_volume", True),
        encoder=rcfg.get("encoder", "auto"),
    )


def check_settings(cfg: Config, platforms: list[str]) -> None:
    """Catch config mistakes before spending time downloading and rendering clips."""
    if "uploadpost" in platforms:
        profile = (cfg.platform("uploadpost").get("profile") or "").strip()
        if not profile or profile.upper() == "YOUR-PROFILE-NAME":
            raise SystemExit(
                "Set platforms.uploadpost.profile in config.yaml to your Upload-Post profile name "
                "(run `claud profiles` to see it)."
            )
        env("UPLOAD_POST_API_KEY")


def run(cfg: Config, *, dry_run: bool = False) -> None:
    platforms = enabled_platforms(cfg)
    if not platforms:
        log.warning("No platforms enabled in config")
    if not dry_run:
        check_settings(cfg, platforms)
    db = DB(cfg.data_dir / "claud.db")
    tw = twitch.Twitch(env("TWITCH_CLIENT_ID"), env("TWITCH_CLIENT_SECRET"))
    streamers = {s.login: s for s in cfg.streamers}

    candidates = find_candidates(cfg, tw, db, platforms)
    log.info("%d clip(s) to post", len(candidates))

    ucfg = cfg.platform("uploadpost")
    for clip, todo in candidates:
        if "uploadpost" in todo and not dry_run:
            used_month, used_today = budget.usage(db, ucfg)
            left = budget.minutes_left_today(ucfg, used_month, used_today)
            if budget.clip_minutes(clip.duration, ucfg) > left:
                log.info("Upload-Post minutes budget: %.1f min left for today, not enough for %r (%.0fs); "
                         "it'll be posted on a later run", left, clip.title, clip.duration)
                todo = [p for p in todo if p != "uploadpost"]
                if not todo:
                    continue
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
