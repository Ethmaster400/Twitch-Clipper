"""Speech-to-text captions with faster-whisper, written as an ASS subtitle file."""
from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("claud")


@dataclass
class Word:
    start: float
    end: float
    text: str


# Caption look adapted from streamclip: heavy font with a thick outline and drop shadow,
# positioned with \pos and a quick "pop" scale-in. Arial Black ships with Windows; elsewhere
# libass falls back to the closest bold font installed.
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Hook,{font},{hook_size},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
DEFAULT_FONT = "Arial Black"
POP_IN = r"\fscx90\fscy90\t(0,80,\fscx100\fscy100)"


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


def add_cuda_dlls() -> None:
    """On Windows, let faster-whisper find the cuBLAS / cuDNN DLLs installed with
    `pip install .[gpu]` (nvidia-* packages), so it can use an NVIDIA GPU without a
    separate CUDA install. Adapted from streamclip."""
    if os.name != "nt":
        return
    site = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for d in glob.glob(str(site / "*" / "bin")):
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


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

    add_cuda_dlls()
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


def group_words(words: list[Word], per_caption: int, max_chars: int = 18) -> list[Word]:
    """Merge words into short punchy caption chunks: at most `per_caption` words and about
    `max_chars` characters, breaking early on long pauses and after sentence punctuation."""
    chunks: list[Word] = []
    current: list[Word] = []

    def flush():
        if current:
            chunks.append(Word(current[0].start, current[-1].end, " ".join(x.text for x in current)))
            current.clear()

    for w in words:
        if current and (
            len(current) >= per_caption
            or w.start - current[-1].end > 0.6
            or len(" ".join(x.text for x in current + [w])) > max_chars
        ):
            flush()
        current.append(w)
        if w.text[-1:] in ".,!?":
            flush()
    flush()
    return chunks


def clean_hook(text: str) -> str:
    """Drop characters the caption font can't draw (emoji) and collapse '!!!' / '???'."""
    text = re.sub(r"[^\w\s.,!?'\"&%$#@:;()+-]", "", text or "")
    text = re.sub(r"([!?.])\1+", r"\1", text)
    text = re.sub(r"\s+([!?.,])", r"\1", text)  # "SHOT 🔥!" would otherwise become "SHOT !"
    return re.sub(r"\s+", " ", text).strip()


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
    font: str = DEFAULT_FONT,
) -> Path:
    """center_y: vertical position of the caption's middle, as a fraction from the top.
    hook: optional text shown in a white box for the first `hook_seconds`, its top edge at `hook_top`."""
    x, cap_y, hook_y = width // 2, int(height * center_y), int(height * hook_top)
    lines = [ASS_HEADER.format(
        width=width, height=height, font=font,
        font_size=int(height * 0.044), hook_size=int(height * 0.033),
    )]
    hook = clean_hook(hook or "")
    if hook:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_seconds)},Hook,,0,0,0,,"
                     f"{{\\pos({x},{hook_y})}}{_escape(hook.upper())}\n")
    for c in chunks:
        end = max(c.end, c.start + 0.3)  # very short words would only flash on screen
        lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(end)},Default,,0,0,0,,"
                     f"{{\\pos({x},{cap_y}){POP_IN}}}{_escape(c.text.upper())}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path
