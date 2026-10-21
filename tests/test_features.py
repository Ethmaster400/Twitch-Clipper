from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from claud import captions, content_filter, hooks, ranking
from claud.twitch import Clip

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def clip(id, views, hours_ago, duration=30.0, title="clip title here"):
    created = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return Clip(id=id, streamer="s", title=title, url=f"https://clips.twitch.tv/{id}", views=views,
                duration=duration, game_id="1", created_at=created)


def test_fast_rising_clip_beats_older_bigger_one():
    old_big = clip("old", views=20000, hours_ago=46)     # ~435 views/hour
    rising = clip("new", views=9000, hours_ago=2)        # 4500 views/hour
    order = [c.id for _, c in ranking.rank([old_big, rising], now=NOW)]
    assert order == ["new", "old"]


def test_duration_and_title_signals():
    assert ranking.duration_score(30) == 1.0
    assert ranking.duration_score(5) == 0.0 and ranking.duration_score(100) == 0.0
    assert ranking.title_score("NO WAY he hit that clutch!") > ranking.title_score("clip")


def test_weights_are_configurable():
    big_long = clip("a", views=10000, hours_ago=10, duration=85)
    small_ideal = clip("b", views=1000, hours_ago=10, duration=30)
    only_views = {"weights": {"velocity": 0, "views": 1, "recency": 0, "duration": 0, "title": 0}}
    only_duration = {"weights": {"velocity": 0, "views": 0, "recency": 0, "duration": 1, "title": 0}}
    assert ranking.rank([big_long, small_ideal], only_views, now=NOW)[0][1].id == "a"
    assert ranking.rank([big_long, small_ideal], only_duration, now=NOW)[0][1].id == "b"


def test_content_filter():
    assert content_filter.blocked_term("streamer gets SWATTED live") == "swatted"
    assert content_filter.blocked_term("a paradox in the speedrun") is None   # whole words only
    assert content_filter.blocked_term("big casino win", {"extra_terms": ["casino"]}) == "casino"
    assert content_filter.blocked_term("nsfw", {"enabled": False}) is None


def test_keyword_hook_and_clean():
    assert hooks.keyword_hook("omg no way he did that") == "THIS REACTION WAS INSANE"
    assert hooks.keyword_hook("") == "NOBODY EXPECTED THIS"
    assert hooks.clean('"He actually hit the 1v5!" 🔥') == "HE ACTUALLY HIT THE 1V5"
    assert hooks.clean("ok") == ""   # too short to use


def test_claude_hook_request_and_fallback(monkeypatch):
    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text="He Hit The Impossible Shot")])

    class FakeClient:
        def __init__(self, **_):
            self.beta = SimpleNamespace(messages=FakeMessages())

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    assert hooks.generate("bro he actually hit it", "insane shot", "s") == "HE HIT THE IMPOSSIBLE SHOT"
    assert calls["model"] == "claude-opus-5-5" and calls["fallbacks"] == "default"
    assert "bro he actually hit it" in calls["messages"][0]["content"]

    class Broken(FakeClient):
        def __init__(self, **_):
            raise RuntimeError("no credentials")

    monkeypatch.setattr(anthropic, "Anthropic", Broken)
    assert hooks.generate("lmao that was hilarious", "", "s") == "HE DID NOT JUST SAY THAT"
    assert hooks.generate("lmao", "", "s", {"use_claude": False}) == "HE DID NOT JUST SAY THAT"


def test_hook_in_ass(tmp_path):
    text = captions.write_ass([], tmp_path / "h.ass", hook="watch this", hook_seconds=2.5).read_text()
    assert "Dialogue: 1,0:00:00.00,0:00:02.50,Hook,,0,0,0,,WATCH THIS" in text


def test_tiktok_drafts_mode(monkeypatch, tmp_path):
    from claud.metadata import PostMeta
    from claud.uploaders import tiktok

    posted = []
    monkeypatch.setattr(tiktok, "_access_token", lambda _: "tok")
    monkeypatch.setattr(tiktok, "_put_chunks", lambda *a: None)

    def fake_post(path, token, payload):
        posted.append((path, payload))
        if path.endswith("/init/"):
            return {"publish_id": "p1", "upload_url": "https://upload"}
        return {"status": "SEND_TO_USER_INBOX"}

    monkeypatch.setattr(tiktok, "_post", fake_post)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1000)
    meta = PostMeta(title="t", description="d", hashtags=["#a"], tags=[])
    assert tiktok.upload(video, meta, {"token_file": "x", "mode": "drafts"}) == "p1"
    assert posted[0][0] == "/post/publish/inbox/video/init/"
    assert "post_info" not in posted[0][1]
    with pytest.raises(ValueError):
        tiktok.upload(video, meta, {"token_file": "x", "mode": "bogus"})


def test_tiktok_auth_sends_pkce(monkeypatch, tmp_path, capsys):
    import hashlib
    import urllib.parse

    from claud.uploaders import tiktok

    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "key")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://localhost/callback")
    sent = {}

    answers = []

    def fake_input(_prompt):
        if not answers:
            url = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("https://"))
            sent["auth"] = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            answers.extend([
                "",                                   # Enter pressed before pasting
                "https://www.tiktok.com/v2/auth/",    # wrong URL: asked again
                # right URL, broken across lines as when copied from a terminal
                f"https://localhost/callback?co\nde=abc&state={sent['auth']['state']}",
            ])
        return answers.pop(0)

    monkeypatch.setattr("webbrowser.open", lambda url: True)

    def fake_token_request(fields):
        sent["token"] = fields
        return {"access_token": "a", "refresh_token": "r", "expires_in": 86400, "obtained_at": 0}

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(tiktok, "_token_request", fake_token_request)
    tiktok.authorize(str(tmp_path / "tok.json"))

    verifier = sent["token"]["code_verifier"]
    assert sent["auth"]["code_challenge_method"] == "S256"
    assert sent["auth"]["code_challenge"] == hashlib.sha256(verifier.encode()).hexdigest()
    assert 43 <= len(verifier) <= 128 and sent["token"]["code"] == "abc"
    assert (tmp_path / "tok.json").exists()


def test_load_audio_and_transcribe_skip_pyav(tmp_path, monkeypatch):
    import subprocess
    import sys
    import types

    import numpy as np

    with_audio, silent = tmp_path / "a.mp4", tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", str(with_audio)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:duration=2",
                    str(silent)], check=True)

    audio = captions.load_audio(with_audio)
    assert audio.dtype == np.float32 and abs(audio.size - 2 * captions.SAMPLE_RATE) < 2000
    assert 0.1 < np.abs(audio).max() <= 1.0
    assert captions.load_audio(silent).size == 0

    seen = {}

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, audio, **kw):
            seen["audio"] = audio
            word = types.SimpleNamespace(start=0.1, end=0.4, word=" hello")
            return [types.SimpleNamespace(words=[word])], None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    assert captions.transcribe(with_audio) == [captions.Word(0.1, 0.4, "hello")]
    assert isinstance(seen["audio"], np.ndarray)   # raw samples, so faster-whisper never calls PyAV
    assert captions.transcribe(silent) == []


def test_whisper_falls_back_to_cpu_when_gpu_libs_missing(tmp_path, monkeypatch):
    import subprocess
    import sys
    import types

    clip = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-shortest", str(clip)], check=True)
    devices = []

    class FakeModel:
        def __init__(self, size, device, compute_type):
            devices.append(device)
            self.device = device

        def transcribe(self, audio, **kw):
            def segments():  # lazy, like faster-whisper: GPU libs load while iterating
                if self.device != "cpu":
                    raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                yield types.SimpleNamespace(words=[types.SimpleNamespace(start=0, end=0.5, word="hi")])
            return segments(), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setattr(captions, "_gpu_failed", False)
    assert captions.transcribe(clip) == [captions.Word(0, 0.5, "hi")]
    assert devices == ["auto", "cpu"]
    captions.transcribe(clip)                 # later clips skip the GPU attempt
    assert devices == ["auto", "cpu", "cpu"]
    with pytest.raises(RuntimeError):         # an explicit cuda setting doesn't silently fall back
        captions.transcribe(clip, device="cuda")


def test_retry_clears_failed_attempts(tmp_path):
    from claud.db import DB, MAX_ATTEMPTS

    db = DB(tmp_path / "t.db")
    clip = Clip(id="c", streamer="s", title="t", url="u", views=1, duration=10, game_id="1")
    db.upsert_clip(clip)
    db.record_post("c", "youtube", remote_id="yt1")
    for _ in range(MAX_ATTEMPTS):
        db.record_post("c", "tiktok", error="render: boom")
    assert not db.needs_post("c", "tiktok")
    assert db.reset_failed() == 1
    assert db.needs_post("c", "tiktok") and not db.needs_post("c", "youtube")
