"""Word-by-word "TikTok style" captions with faster-whisper (optional dependency).

pip install faster-whisper   ->  runs on CPU (int8) or CUDA automatically.
Captions are off by default for live clipping: they cost CPU and seconds, and
being first matters more than being pretty. Turn them on per session."""
from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path

log = logging.getLogger("primeclips.captions")
_model = None
_lock = threading.Lock()


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _get_model(name: str, threads: int):
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel  # type: ignore
            try:
                _model = WhisperModel(name, device="cuda", compute_type="float16")
            except Exception:
                _model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
        return _model


def transcribe(path: Path, model: str = "base", threads: int = 2) -> list[tuple[float, float, str]]:
    m = _get_model(model, threads)
    segments, _ = m.transcribe(str(path), word_timestamps=True, vad_filter=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            if w.word.strip():
                words.append((float(w.start), float(w.end), w.word.strip()))
    return words


def _ts(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_ass(words: list[tuple[float, float, str]], dst: Path, width: int = 1080, height: int = 1920,
              margin_v: int = 560, max_words: int = 3) -> Path:
    """Groups of up to 3 words; the word being spoken pops in yellow."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,Arial,{int(width * 0.085)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > 0.6):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    lines = []
    for g in groups:
        for i, (s, e, _) in enumerate(g):
            end = g[i + 1][0] if i + 1 < len(g) else e
            parts = []
            for j, (_, _, txt) in enumerate(g):
                txt = txt.upper().replace("{", "").replace("}", "")
                parts.append("{\\c&H00E5FF&\\fscx112\\fscy112}" + txt + "{\\r}" if j == i else txt)
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(max(end, s + 0.05))},Pop,,0,0,0,,{' '.join(parts)}")
    dst.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return dst
