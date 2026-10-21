"""Speech-to-text captions with faster-whisper, written as an ASS subtitle file."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("claud")


@dataclass
class Word:
    start: float
    end: float
    text: str


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,{margin_v},1
Style: Hook,DejaVu Sans,{hook_size},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,14,0,8,90,90,{hook_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


SAMPLE_RATE = 16000  # what Whisper expects


def load_audio(video: Path) -> np.ndarray:
    """Mono 16 kHz float32 audio via ffmpeg; empty if the clip has no audio.

    faster-whisper's own decoder goes through PyAV, whose API changes between releases
    (PyAV 19 broke faster-whisper 1.2), so decode with the ffmpeg we already require."""
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True,
    )
    if result.returncode != 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0


_gpu_failed = False  # remember a failed GPU attempt so later clips go straight to CPU


def transcribe(video: Path, model_size: str = "small", device: str = "auto") -> list[Word]:
    """device: auto (GPU if it works, else CPU), cuda or cpu."""
    global _gpu_failed
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("Captions need faster-whisper: pip install '.[captions]'") from e

    audio = load_audio(video)
    if audio.size < SAMPLE_RATE // 2:  # no audio, or under half a second of it
        return []

    devices = ["cpu"] if device == "auto" and _gpu_failed else [device]
    if devices == ["auto"]:
        devices.append("cpu")
    for i, dev in enumerate(devices):
        try:
            model = WhisperModel(model_size, device=dev, compute_type="int8")
            segments, _info = model.transcribe(audio, word_timestamps=True, vad_filter=True)
            # segments is lazy: the GPU libraries are only loaded while iterating it.
            return [
                Word(w.start, w.end, w.word.strip())
                for seg in segments
                for w in (seg.words or [])
                if w.word.strip()
            ]
        except Exception as e:
            if i == len(devices) - 1:
                raise
            # e.g. an NVIDIA GPU without the CUDA libraries (cublas64_12.dll not found)
            _gpu_failed = True
            log.warning("Whisper couldn't use the GPU (%s); using the CPU instead", e)
    return []


def group_words(words: list[Word], per_caption: int) -> list[Word]:
    """Merge words into short punchy caption chunks, breaking early on long pauses."""
    chunks: list[Word] = []
    current: list[Word] = []
    for w in words:
        if current and (len(current) >= per_caption or w.start - current[-1].end > 0.6):
            chunks.append(Word(current[0].start, current[-1].end, " ".join(x.text for x in current)))
            current = []
        current.append(w)
    if current:
        chunks.append(Word(current[0].start, current[-1].end, " ".join(x.text for x in current)))
    return chunks


def _ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(
    chunks: list[Word], path: Path, width: int = 1080, height: int = 1920, center_y: float = 0.7,
    hook: str | None = None, hook_seconds: float = 3.0, hook_top: float = 0.07,
) -> Path:
    """center_y: vertical position of the caption's middle, as a fraction from the top.
    hook: optional text shown in a white box for the first `hook_seconds`, its top edge at `hook_top`."""
    font_size = int(height * 0.045)
    margin_v = max(0, int(height * (1 - center_y) - font_size / 2))
    lines = [ASS_HEADER.format(
        width=width, height=height, font_size=font_size, margin_v=margin_v,
        hook_size=int(height * 0.036), hook_margin=int(height * hook_top),
    )]
    if hook:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_seconds)},Hook,,0,0,0,,{_escape(hook.upper())}\n")
    for c in chunks:
        lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},Default,,0,0,0,,{_escape(c.text.upper())}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path
