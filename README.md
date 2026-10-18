# Claud

Automatically reposts popular Twitch clips from **streamers who've given permission** to YouTube Shorts and TikTok.

```
Twitch Helix (top clips) → yt-dlp download → Whisper captions → ffmpeg 9:16 render → YouTube + TikTok
                                                                            ↳ SQLite: never double-post, retry failures (max 3)
```

## Setup

Requires Python 3.10+ and `ffmpeg` (with libass) on the PATH.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[captions,dev]'
cp .env.example .env              # fill in API keys
cp config.example.yaml config.yaml  # add your streamers
```

### API credentials

| Platform | Where | Notes |
|---|---|---|
| Twitch | [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps) | Client ID + secret → `.env` |
| YouTube | Google Cloud Console → enable **YouTube Data API v3** → OAuth client (Desktop) | Save JSON as `secrets/youtube_client_secret.json`, then `claud auth youtube`. Default quota (10k units/day) allows ~6 uploads/day; request more if needed. Unverified apps' uploads may be locked private until the app passes Google's audit. |
| TikTok | [developers.tiktok.com](https://developers.tiktok.com/) → app with **Content Posting API** + `video.publish` | Keys → `.env`, then `claud auth tiktok`. Until TikTok audits the app, posts can only be `SELF_ONLY` (private) — set `privacy: SELF_ONLY` while testing. |

## Usage

```bash
claud run --dry-run   # find + download + render, no upload (check data/out/)
claud run             # full pipeline once
claud loop --every 60 # run every hour
claud history         # what's been posted / failed
claud render in.mp4 out.mp4 --captions   # test the editor on a local file
```

Or schedule with cron:

```
0 * * * * cd /path/to/claud && .venv/bin/claud run >> data/cron.log 2>&1
```

## Config highlights (`config.yaml`)

- `streamers[].permission` is **required**. Record how/when each streamer agreed.
- `selection`: lookback window, minimum views, maximum duration, posts per run.
- `render.layout`: `blur` (full frame over a blurred background) or `crop` (center crop, fills the screen).
- `metadata`: title, description and hashtag templates (`{title} {streamer} {game} {url} {hashtags}`).

## Tests

```bash
pytest
```
