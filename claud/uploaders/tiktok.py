"""TikTok upload via the Content Posting API.

Two modes (platforms.tiktok.mode):
- direct (default): Direct Post, published straight to the profile. Until TikTok audits
  your app, posts are restricted to SELF_ONLY (private) visibility.
- drafts: uploads to the creator's TikTok inbox; you add the caption and tap post in the app.
  Works without the audit. Drafts mode adapted from coltonalmeida/twitch-clipper (MIT).
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

from ..config import env
from ..metadata import PostMeta, tiktok_caption

API = "https://open.tiktokapis.com/v2"
MB = 1024 * 1024

log = logging.getLogger("claud")


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for TikTok's PKCE. TikTok's S256 challenge is the
    hex-encoded SHA-256 of the verifier, not the base64url encoding standard OAuth uses."""
    verifier = secrets.token_urlsafe(48)  # 64 chars from [A-Za-z0-9_-]
    return verifier, hashlib.sha256(verifier.encode()).hexdigest()


def authorize(token_file: str) -> None:
    """One-time OAuth: open the URL, approve, then paste the URL you were redirected to."""
    state = secrets.token_urlsafe(16)
    verifier, challenge = pkce_pair()
    params = {
        "client_key": env("TIKTOK_CLIENT_KEY"),
        "scope": "user.info.basic,video.publish,video.upload",
        "response_type": "code",
        "redirect_uri": env("TIKTOK_REDIRECT_URI"),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)
    print("Approve access in your browser. If it didn't open, copy this URL into it:\n")
    print(url)
    webbrowser.open(url)
    print(f"\nAfter approving, the browser goes to {env('TIKTOK_REDIRECT_URI')}?code=... "
          "(the page itself shows an error, that's fine).\nCopy that whole address from the address bar.")
    query: dict = {}
    while "code" not in query and "error" not in query:
        # Remove whitespace: long URLs copied from a terminal often pick up line breaks.
        redirected = "".join(input("\nPaste the address here and press Enter (Ctrl+C to quit): ").split())
        query = urllib.parse.parse_qs(urllib.parse.urlparse(redirected).query)
        if redirected and "code" not in query and "error" not in query:
            print("That's not the address TikTok sent you back to; it should contain 'code='. Try again.")
    if "error" in query:
        raise RuntimeError(f"TikTok login failed: {query.get('error_description', query['error'])[0]}")
    if query.get("state", [""])[0] != state:
        raise RuntimeError("That address is from an older login attempt; run `claud auth tiktok` again")
    token = _token_request(
        {
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": env("TIKTOK_REDIRECT_URI"),
            "code_verifier": verifier,
        }
    )
    _save(token_file, token)
    print(f"Saved TikTok token to {token_file}")


def _token_request(fields: dict) -> dict:
    r = requests.post(
        f"{API}/oauth/token/",
        data={"client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"), **fields},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if "access_token" not in body:
        raise RuntimeError(f"TikTok token error: {body}")
    body["obtained_at"] = time.time()
    return body


def _save(token_file: str, token: dict) -> None:
    Path(token_file).parent.mkdir(parents=True, exist_ok=True)
    Path(token_file).write_text(json.dumps(token, indent=2))


def _access_token(token_file: str) -> str:
    path = Path(token_file)
    if not path.exists():
        raise RuntimeError("No TikTok token; run `claud auth tiktok` first")
    token = json.loads(path.read_text())
    if time.time() > token["obtained_at"] + token["expires_in"] - 300:
        token = _token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
        _save(token_file, token)
    return token["access_token"]


def _post(path: str, access_token: str, payload: dict) -> dict:
    r = requests.post(
        f"{API}{path}",
        json=payload,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        timeout=60,
    )
    body = r.json()
    err = body.get("error", {})
    if r.status_code != 200 or err.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok {path} failed: {err or body}")
    return body["data"]


def chunk_plan(size: int) -> tuple[int, int]:
    """Return (chunk_size, total_chunk_count) following TikTok's rules:
    files up to 64MB go as one chunk; otherwise 5-64MB chunks, with the last
    chunk absorbing the remainder (count = floor(size / chunk_size))."""
    if size <= 64 * MB:
        return size, 1
    chunk = 10 * MB
    return chunk, size // chunk


def upload(video: Path, meta: PostMeta, cfg: dict) -> str:
    token = _access_token(cfg["token_file"])
    mode = cfg.get("mode", "direct")
    if mode not in ("direct", "drafts"):
        raise ValueError(f"Unknown TikTok mode {mode!r} (use 'direct' or 'drafts')")

    size = video.stat().st_size
    chunk_size, chunks = chunk_plan(size)
    source_info = {
        "source": "FILE_UPLOAD",
        "video_size": size,
        "chunk_size": chunk_size,
        "total_chunk_count": chunks,
    }
    if mode == "drafts":
        # Drafts take no caption or privacy; they're set in the app when posting.
        init = _post("/post/publish/inbox/video/init/", token, {"source_info": source_info})
        log.info("TikTok draft caption to paste: %s", tiktok_caption(meta))
    else:
        init = _post("/post/publish/video/init/", token, {
            "post_info": _post_info(token, meta, cfg),
            "source_info": source_info,
        })
    publish_id, upload_url = init["publish_id"], init["upload_url"]
    _put_chunks(video, upload_url, size, chunk_size, chunks)
    return _wait_for_publish(token, publish_id)


def _post_info(token: str, meta: PostMeta, cfg: dict) -> dict:
    creator = _post("/post/publish/creator_info/query/", token, {})
    privacy = cfg.get("privacy", "PUBLIC_TO_EVERYONE")
    if privacy not in creator.get("privacy_level_options", []):
        raise RuntimeError(
            f"TikTok privacy {privacy!r} not allowed for this account/app; "
            f"allowed: {creator.get('privacy_level_options')} (unaudited apps can only use SELF_ONLY)"
        )

    return {
        "title": tiktok_caption(meta),
        "privacy_level": privacy,
        "disable_duet": False,
        "disable_comment": False,
        "disable_stitch": False,
        "video_cover_timestamp_ms": 1000,
    }


def _put_chunks(video: Path, upload_url: str, size: int, chunk_size: int, chunks: int) -> None:
    with video.open("rb") as f:
        for i in range(chunks):
            start = i * chunk_size
            end = size if i == chunks - 1 else start + chunk_size
            f.seek(start)
            data = f.read(end - start)
            r = requests.put(
                upload_url,
                data=data,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {start}-{end - 1}/{size}",
                },
                timeout=300,
            )
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok chunk {i + 1}/{chunks} upload failed: {r.status_code} {r.text}")


def _wait_for_publish(token: str, publish_id: str, timeout_s: int = 600) -> str:
    log.info("Uploaded; waiting for TikTok to finish processing (usually under a minute)...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _post("/post/publish/status/fetch/", token, {"publish_id": publish_id})
        state = status.get("status")
        if state in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return publish_id
        if state == "FAILED":
            raise RuntimeError(f"TikTok publish failed: {status.get('fail_reason')}")
        time.sleep(5)
    raise RuntimeError(f"TikTok publish {publish_id} still processing after {timeout_s}s")
