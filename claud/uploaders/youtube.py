"""YouTube Shorts upload via the YouTube Data API v3.

A vertical video of 3 minutes or less is automatically treated as a Short.
"""
from __future__ import annotations

from pathlib import Path

from ..metadata import PostMeta

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def authorize(client_secrets: str, token_file: str) -> None:
    """One-time interactive OAuth. Prints a URL to open in your browser."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
    creds = flow.run_local_server(port=8765, open_browser=False)
    Path(token_file).parent.mkdir(parents=True, exist_ok=True)
    Path(token_file).write_text(creds.to_json())
    print(f"Saved YouTube token to {token_file}")


def _credentials(token_file: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not Path(token_file).exists():
        raise RuntimeError("No YouTube token; run `claud auth youtube` first")
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        Path(token_file).write_text(creds.to_json())
    return creds


def upload(video: Path, meta: PostMeta, cfg: dict) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=_credentials(cfg["token_file"]), cache_discovery=False)
    title = meta.title if "#shorts" in meta.title.lower() else meta.title[:91] + " #Shorts"
    body = {
        "snippet": {
            "title": title,
            "description": meta.description,
            "tags": meta.tags,
            "categoryId": str(cfg.get("category_id", "20")),
        },
        "status": {
            "privacyStatus": cfg.get("privacy", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _status, response = request.next_chunk()
    return response["id"]
