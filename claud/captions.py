"""Speech-to-text captions with faster-whisper, written as an ASS subtitle file."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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


def transcribe(video: Path, model_size: str = "small") -> list[Word]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("Captions need faster-whisper: pip install '.[captions]'") from e

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _info = model.transcribe(str(video), word_timestamps=True, vad_filter=True)
    return [
        Word(w.start, w.end, w.word.strip())
        for seg in segments
        for w in (seg.words or [])
        if w.word.strip()
    ]


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
