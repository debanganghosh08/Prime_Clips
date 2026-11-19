"""Word-by-word "TikTok style" captions with faster-whisper (optional dependency).

pip install faster-whisper   ->  runs on CPU (int8) or CUDA automatically.
Captions are off by default for live clipping: they cost CPU and seconds, and
being first matters more than being pretty. Turn them on per session."""
from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import threading
from pathlib import Path

from .ffmpeg import popen_kwargs, which

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
            device = os.environ.get("PRIMECLIPS_WHISPER_DEVICE", "auto").lower()  # auto|cpu|cuda
            if device in ("auto", "cuda"):
                try:
                    import numpy as np
                    m = WhisperModel(name, device="cuda", compute_type="float16")
                    # A GPU can be detected while the CUDA libraries (cuBLAS/cuDNN) are
                    # missing, and that only fails at the first transcribe. Prove it works now.
                    list(m.transcribe(np.zeros(16000, np.float32))[0])
                    _model = m
                    log.info("captions: faster-whisper on CUDA")
                except Exception as e:
                    if device == "cuda":
                        raise
                    log.info("captions: CUDA unavailable (%s), using CPU", str(e)[:80])
            if _model is None:
                _model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
        return _model


def _load_audio(path: Path, ffmpeg: str):
    """16 kHz mono float32, decoded by our own ffmpeg. Handing faster-whisper an array
    (instead of a path) avoids its PyAV decoder, whose version mismatches are the #1
    reason captions break on fresh installs."""
    import numpy as np  # installed with faster-whisper
    out = subprocess.run([which(ffmpeg) or ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                          "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
                         capture_output=True, timeout=3600, **popen_kwargs(True))
    return np.frombuffer(out.stdout, np.int16).astype(np.float32) / 32768.0


def transcribe(path: Path, model: str = "base", threads: int = 2,
               ffmpeg: str = "ffmpeg") -> list[tuple[float, float, str]]:
    m = _get_model(model, threads)
    audio = _load_audio(path, ffmpeg)
    if not len(audio):
        return []
    segments, _ = m.transcribe(audio, word_timestamps=True, vad_filter=True)
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
              pos: tuple[int, int] | None = None, max_words: int = 3) -> Path:
    """Bold karaoke captions: groups of up to 3 UPPERCASE words, white with a heavy black
    outline; the word being spoken lights up electric yellow (#FFE500) and each phrase pops in.
    `pos` = (x, y) centre of the caption line (see render.caption_anchor)."""
    x, y = pos or (width // 2, int(height * 0.7))
    font = os.environ.get("PRIMECLIPS_CAPTION_FONT", "Impact")
    size = int(width * 0.067)  # 72 px on a 1080-wide short
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,6,2,5,40,40,0,1

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
                # colour-only highlight: scaling one word would reflow the centred line
                # and make the captions visibly jitter on every word change
                parts.append("{\\c&H00E5FF&}" + txt + "{\\c&HFFFFFF&}" if j == i else txt)
            # each new phrase pops in once (88% -> 100% in 140 ms)
            pop = "\\fscx88\\fscy88\\t(0,140,\\fscx100\\fscy100)" if i == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(max(end, s + 0.05))},Pop,,0,0,0,,"
                         f"{{\\pos({x},{y}){pop}}}{' '.join(parts)}")
    dst.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return dst
