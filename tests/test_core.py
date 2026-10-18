import json
import subprocess
from pathlib import Path

import pytest

from claud import captions, metadata, render
from claud.db import DB, MAX_ATTEMPTS
from claud.twitch import Clip, select_clips
from claud.uploaders.tiktok import MB, chunk_plan


def make_clip(**kw):
    base = dict(id="AbcClip", streamer="CoolStreamer", title="insane clutch", url="https://clips.twitch.tv/AbcClip",
                views=1000, duration=30.0, game_id="1", game_name="Counter-Strike 2")
    base.update(kw)
    return Clip(**base)


def test_select_clips_filters_and_sorts():
    clips = [make_clip(id="a", views=100), make_clip(id="b", views=5000), make_clip(id="c", views=900, duration=90)]
    assert [c.id for c in select_clips(clips, min_views=500, max_duration_s=60)] == ["b"]


def test_metadata_build():
    cfg = {"title_template": "{title} | {streamer}", "base_hashtags": ["#twitch", "#shorts"],
           "description_template": "{title}\n{url}\n{hashtags}"}
    meta = metadata.build(make_clip(), cfg, ["#cool"])
    assert meta.title == "insane clutch | CoolStreamer"
    assert meta.hashtags == ["#CoolStreamer", "#CounterStrike2", "#cool", "#twitch", "#shorts"]
    assert "https://clips.twitch.tv/AbcClip" in meta.description
    assert len(metadata.build(make_clip(title="x" * 300), cfg).title) == 100


def test_db_dedupe_and_retry(tmp_path):
    db = DB(tmp_path / "t.db")
    clip = make_clip()
    db.upsert_clip(clip)
    assert db.needs_post(clip.id, "youtube")
    db.record_post(clip.id, "youtube", remote_id="yt123")
    assert not db.needs_post(clip.id, "youtube")
    for _ in range(MAX_ATTEMPTS):
        assert db.needs_post(clip.id, "tiktok")
        db.record_post(clip.id, "tiktok", error="boom")
    assert not db.needs_post(clip.id, "tiktok")


def test_tiktok_chunk_plan():
    assert chunk_plan(20 * MB) == (20 * MB, 1)
    size = 150 * MB + 123
    chunk, count = chunk_plan(size)
    assert count == 15 and size - chunk * (count - 1) < 128 * MB


def test_caption_grouping_and_ass(tmp_path):
    words = [captions.Word(0.0, 0.3, "no"), captions.Word(0.3, 0.6, "way"), captions.Word(0.6, 0.9, "he"),
             captions.Word(0.9, 1.2, "hit"), captions.Word(3.0, 3.4, "that")]
    chunks = captions.group_words(words, 3)
    assert [c.text for c in chunks] == ["no way he", "hit", "that"]
    path = captions.write_ass(chunks, tmp_path / "c.ass")
    text = path.read_text()
    assert "Dialogue: 0,0:00:00.00,0:00:00.90,Default,,0,0,0,,NO WAY HE" in text


@pytest.mark.parametrize("layout", ["blur", "crop"])
def test_render_vertical(tmp_path, layout):
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", str(src)],
        check=True,
    )
    subs = captions.write_ass([captions.Word(0, 1.5, "hello world")], tmp_path / "s.ass")
    out = render.render_vertical(src, tmp_path / "out.mp4", layout=layout, subtitles=subs)
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        check=True, capture_output=True, text=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in probe["streams"])
