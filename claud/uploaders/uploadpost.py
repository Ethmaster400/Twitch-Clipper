"""Upload-Post destination: post to TikTok and YouTube Shorts through upload-post.com.

Upload-Post is already approved by TikTok and Google, so posts go out publicly without
waiting on our own app reviews. You connect your TikTok and YouTube accounts to a profile
in the Upload-Post dashboard; Claud uploads each video once and Upload-Post publishes it
to every platform listed in `platforms`.

Uses Upload-Post's official Python package (`upload-post`, MIT).
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import env
from ..metadata import PostMeta, tiktok_caption

log = logging.getLogger("claud")

YOUTUBE_TITLE_MAX = 100


def client():
    from upload_post import UploadPostClient

    return UploadPostClient(api_key=env("UPLOAD_POST_API_KEY"))


def youtube_title(meta: PostMeta) -> str:
    """Title with #Shorts, within YouTube's 100-character limit."""
    if "#shorts" in meta.title.lower():
        return meta.title[:YOUTUBE_TITLE_MAX]
    return meta.title[: YOUTUBE_TITLE_MAX - len(" #Shorts")].rstrip() + " #Shorts"


def build_options(meta: PostMeta, cfg: dict) -> dict:
    """Keyword arguments for UploadPostClient.upload_video, from post metadata and config."""
    platforms = list(cfg.get("platforms") or ["tiktok", "youtube"])
    options = {
        "title": meta.title,
        "user": cfg.get("profile") or "",
        "platforms": platforms,
        "async_upload": True,
    }
    if cfg.get("queue"):
        options["add_to_queue"] = True  # post in the time slots set in the Upload-Post dashboard
    if "tiktok" in platforms:
        options["tiktok_title"] = tiktok_caption(meta)
        if cfg.get("tiktok_privacy"):
            options["privacy_level"] = cfg["tiktok_privacy"]
    if "youtube" in platforms:
        options.update(
            youtube_title=youtube_title(meta),
            youtube_description=meta.description,
            tags=meta.tags[:15],
            categoryId=str(cfg.get("youtube_category_id", "20")),  # 20 = Gaming
            privacyStatus=cfg.get("youtube_privacy", "public"),
            selfDeclaredMadeForKids=False,
        )
    return options


def upload(video: Path, meta: PostMeta, cfg: dict) -> str:
    if not cfg.get("profile"):
        raise RuntimeError("Set platforms.uploadpost.profile to your Upload-Post profile name")
    options = build_options(meta, cfg)
    log.info("Sending to Upload-Post profile %r for %s", options["user"], ", ".join(options["platforms"]))
    response = client().upload_video(str(video), **options)
    if isinstance(response, dict) and response.get("success") is False:
        raise RuntimeError(f"Upload-Post rejected the upload: {response}")
    for warning in (response or {}).get("warnings", []) if isinstance(response, dict) else []:
        log.warning("Upload-Post: %s", warning)
    ident = next(
        (str(response[k]) for k in ("request_id", "job_id") if isinstance(response, dict) and response.get(k)),
        "submitted",
    )
    log.info("Upload-Post accepted it (%s); check the dashboard for the final result", ident)
    return ident


def list_profiles() -> list[str]:
    """Profile names on the Upload-Post account, to check the API key and profile setting."""
    response = client().list_users()
    if isinstance(response, dict):
        users = response.get("profiles") or response.get("users") or []
    else:
        users = response
    names = []
    for user in users or []:
        if isinstance(user, dict):
            names.append(str(user.get("username") or user.get("name") or user))
        else:
            names.append(str(user))
    return names


def status(request_id: str) -> dict:
    """What Upload-Post reports for one upload (per-platform results), as returned by its API."""
    return client().get_status(request_id)
