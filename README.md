# Claud

Automatically reposts popular Twitch clips from **streamers who've given permission** to YouTube Shorts and TikTok.

```
Twitch Helix (clips) → title filter → rank → yt-dlp download → facecam detect → Whisper captions
  → Claude hook → ffmpeg 9:16 render → YouTube + TikTok      (SQLite: never double-post, retry failures up to 3x)
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
| TikTok | [developers.tiktok.com](https://developers.tiktok.com/) → app with **Login Kit** + **Content Posting API**, scopes `video.publish` + `video.upload` | Keys → `.env`, then `claud auth tiktok`. Until TikTok audits the app, direct posts can only be `SELF_ONLY` (private). Set `mode: drafts` to send videos to your TikTok inbox instead and post them from the app; the log prints a caption to paste. |
| Anthropic (optional) | [console.anthropic.com](https://console.anthropic.com/) | `ANTHROPIC_API_KEY` → `.env`. Claude writes the hook line; without a key a keyword fallback is used. |

## Usage

To upload by hand instead of through the APIs (no TikTok/YouTube keys needed), set
`platforms.manual.enabled: true` and turn the others off. Each run copies new videos into
`data/ready/` with a `.txt` of the caption to paste, e.g. into TikTok Studio
(tiktok.com/tiktokstudio), which can also schedule posts.


```bash
claud run --dry-run   # find + download + render, no upload (check data/out/)
claud run             # full pipeline once
claud loop --every 60 # run every hour
claud history         # what's been posted / failed
claud render in.mp4 out.mp4 --captions   # test the editor on a local file
```

On Windows, schedule a daily run with one command (output goes to `data\claud.log`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule_daily.ps1 -At 09:00
```

Or schedule with cron:

```
0 * * * * cd /path/to/claud && .venv/bin/claud run >> data/cron.log 2>&1
```

## Config highlights (`config.yaml`)

- `streamers[].permission` is **required**. Record how/when each streamer agreed.
- `selection`: lookback window, minimum views, maximum duration, posts per run.
- `ranking`: which clips go first. Signals are scaled 0–1 and weighted: views per hour (velocity),
  total views, recency, length (15–60s scores best) and an energetic title. A clip taking off right now
  beats an older one with more total views.
- `content_filter`: skips clips whose titles mention NSFW content, doxxing, swatting or self-harm (whole words). Add your own with `extra_terms`.
- `hook`: a 4–8 word all-caps line in a white box for the first 3 seconds, written by Claude from the transcript.
  It goes at the top in the blur layout and just under the captions in the split layout, so it never covers the streamer's face.
- `render.layout`: `auto` (default: facecam on top when one is found, otherwise fit + blurred background),
  `blur`, `crop` (center crop, fills the screen) or `split`. A streamer can override it with their own `layout`.

### Facecam layout

With `layout: auto`, every clip is checked for a webcam overlay:

1. 16 frames are sampled across the clip and run through OpenCV's YuNet face detector (model bundled in `claud/models/`).
2. A face that stays in the same spot in most frames is a facecam. Faces in gameplay come and go,
   and a face that fills the frame is a full-screen camera stream, so neither counts.
3. The overlay's borders are where the picture changes from still (webcam) to moving (gameplay).
   A side with no visible border, such as a cam in a corner, is extended to the frame edge.

Found → the facecam goes on top, gameplay below, captions on the seam. Not found → the full clip is fitted over a
blurred copy of itself.

Check what it sees on any clip:

```bash
claud detect https://clips.twitch.tv/SomeClip --preview box.png   # prints the region, draws it on a frame
claud render clip.mp4 out.mp4                                       # auto layout, as the pipeline would do it
```

If detection gets a streamer wrong, pin the region in `config.yaml` as `facecam: [x, y, w, h]` (fractions of
the frame, the same numbers `claud detect` prints). Set `gameplay: [x, y, w, h]` to choose which part of
the frame fills the bottom half (default: the centre). `render.facecam_height` (default 0.35) sets how much of the
video the cam gets. Set `render.detect_facecam: false` to turn detection off.

## Credits

Clip ranking, the title filter, the hook overlay and TikTok drafts mode are adapted from
[coltonalmeida/twitch-clipper](https://github.com/coltonalmeida/twitch-clipper) (MIT). See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Tests

```bash
pytest
```
