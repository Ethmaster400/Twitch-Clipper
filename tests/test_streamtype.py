import json
import subprocess
from pathlib import Path

import pytest

from claud import pipeline, render, streamtype


def test_classify():
    assert streamtype.classify("Just Chatting") == "irl"
    assert streamtype.classify("IRL") == "irl" and streamtype.classify("music") == "irl"
    assert streamtype.classify("Minecraft") == "gaming"
    assert streamtype.classify("") == "gaming"                       # unknown category
    assert streamtype.classify("Sports", ["sports"]) == "irl"       # extra IRL categories from config


def test_layout_follows_stream_type():
    window = render.Rect(0.5, 0, 0.3, 1)
    cam = render.Rect(0.75, 0, 0.25, 0.25)
    kw = dict(src=Path("x.mp4"), detect=lambda _: cam, find_face=lambda _: window)

    assert pipeline.resolve_layout({}, None, stream_type="gaming", **kw) == ("split", cam)
    assert pipeline.resolve_layout({}, None, stream_type="irl", **kw) == ("face", window)
    # IRL clip with no clear face: blurred full frame
    no_face = dict(kw, find_face=lambda _: None)
    assert pipeline.resolve_layout({}, None, stream_type="irl", **no_face) == ("blur", None)
    # config can change the mapping per type
    rcfg = {"layout_by_type": {"irl": "blur"}}
    assert pipeline.resolve_layout(rcfg, None, stream_type="irl", **kw) == ("blur", None)
    # a layout set for the streamer still wins
    from claud.config import Streamer
    pinned = Streamer("kaicenat", "yes", layout="crop")
    assert pipeline.resolve_layout({}, pinned, stream_type="irl", **kw) == ("crop", None)


def test_window_around_centres_on_face_and_stays_in_frame():
    from claud.facecam import window_around

    w = window_around((900, 100, 100, 100), 1280, 720)     # face centred at x=950 of 1280
    assert w.w == pytest.approx(720 * 9 / 16 / 1280, abs=1e-3) and w.h == 1
    assert w.x <= 950 / 1280 <= w.x + w.w
    assert w.x + w.w <= 1.0001
    edge = window_around((1220, 100, 60, 60), 1280, 720)   # face at the right edge: clamped
    assert edge.x + edge.w == pytest.approx(1.0, abs=1e-3)


def test_face_window_finds_person_off_centre(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    from synth import make_stream

    from claud import facecam

    # a big "camera" picture on the right side of the frame, like an IRL stream
    src = make_stream(tmp_path / "irl.mp4", (760, 0, 520, 720), seconds=2)
    window = facecam.face_window(src)
    assert window is not None
    assert window.x > 0.45                                  # moved right, towards the person
    out = render.render_vertical(src, tmp_path / "out.mp4", layout="face", window=window, encoder="cpu")
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                      check=True, capture_output=True, text=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)


def test_face_layout_requires_window():
    with pytest.raises(ValueError):
        render.build_filter("face", 1080, 1920)
