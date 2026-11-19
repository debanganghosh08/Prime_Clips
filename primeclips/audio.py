"""Loudness meter. Screams, explosions and hype moments are loud: we decode only the
audio of each finished segment at 8 kHz mono (tiny) and compute RMS in dBFS."""
from __future__ import annotations

import array
import math
import subprocess
import sys
from pathlib import Path
from typing import Iterator

from .ffmpeg import popen_kwargs, which

RATE = 8000


def _pcm_to_db(data: bytes, window: float) -> list[float]:
    a = array.array("h")
    a.frombytes(data[: len(data) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    n = max(1, int(RATE * window))
    out = []
    for i in range(0, len(a), n):
        chunk = a[i:i + n]
        if len(chunk) < n // 4:
            break
        rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
        out.append(20 * math.log10(rms / 32768 + 1e-9))
    return out


def segment_levels(ffmpeg: str, path: Path, window: float = 0.5) -> list[float]:
    """dBFS per `window` seconds for one buffer segment. Empty if it has no audio."""
    try:
        proc = subprocess.run([which(ffmpeg) or ffmpeg, "-hide_banner", "-loglevel", "quiet",
                               "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE),
                               "-f", "s16le", "pipe:1"],
                              capture_output=True, timeout=30, **popen_kwargs(True))
        return _pcm_to_db(proc.stdout, window)
    except Exception:
        return []


def file_levels(ffmpeg: str, path: Path, window: float = 1.0) -> Iterator[tuple[float, float]]:
    """Stream (t, dBFS) for a whole file (VOD mode) without loading it into memory."""
    proc = subprocess.Popen([which(ffmpeg) or ffmpeg, "-hide_banner", "-loglevel", "quiet",
                             "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE),
                             "-f", "s16le", "pipe:1"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **popen_kwargs(True))
    chunk = int(RATE * window) * 2
    t = 0.0
    try:
        while True:
            data = proc.stdout.read(chunk)
            if not data:
                break
            for db in _pcm_to_db(data, window):
                yield t, db
                t += window
    finally:
        proc.kill()
