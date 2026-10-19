import pytest

pytest.importorskip("cv2")
pytest.importorskip("skimage")

from claud import facecam  # noqa: E402
from synth import make_stream  # noqa: E402

W, H = 1280, 720


@pytest.mark.parametrize(
    "cam",
    [
        (960, 0, 320, 240),     # top-right corner
        (0, 440, 373, 280),     # bottom-left corner
        (0, 0, 256, 192),       # small, top-left
        (820, 380, 360, 270),   # floating, not touching any edge
    ],
)
def test_detects_overlay(tmp_path, cam):
    rect = facecam.detect(make_stream(tmp_path / "s.mp4", cam))
    assert rect is not None
    truth = (cam[0] / W, cam[1] / H, cam[2] / W, cam[3] / H)
    for got, want in zip((rect.x, rect.y, rect.w, rect.h), truth):
        assert got == pytest.approx(want, abs=0.02)


def test_no_face_means_no_facecam(tmp_path):
    assert facecam.detect(make_stream(tmp_path / "s.mp4")) is None


def test_fullscreen_camera_is_not_an_overlay(tmp_path):
    assert facecam.detect(make_stream(tmp_path / "s.mp4", fullscreen_face=True)) is None


def test_persistent_face_ignores_flickering_faces():
    stable = (100, 50, 40, 40)
    frames = [[stable] for _ in range(10)]
    frames[3].append((400, 300, 40, 40))  # a face that shows up in one gameplay frame
    assert facecam.persistent_face(frames, 10) == stable
    assert facecam.persistent_face([[stable]] + [[] for _ in range(9)], 10) is None
