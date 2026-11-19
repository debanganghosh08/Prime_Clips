"""Thin, CPU-friendly wrappers around ffmpeg / ffprobe.

Design rule: never re-encode unless we have to. Cutting from the replay buffer is
pure stream copy (near-zero CPU); only the 9:16 render touches the encoder, and it
prefers the GPU (NVENC / QuickSync / AMF) when one is present."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Sequence

log = logging.getLogger("primeclips.ffmpeg")

_BELOW_NORMAL = 0x00004000  # Windows BELOW_NORMAL_PRIORITY_CLASS
_NO_WINDOW = 0x08000000     # Windows CREATE_NO_WINDOW


def popen_kwargs(low_priority: bool = True) -> dict:
    """Spawn children at low priority so the game / stream / PC stay smooth."""
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = _NO_WINDOW | (_BELOW_NORMAL if low_priority else 0)
    elif low_priority:
        kw["preexec_fn"] = lambda: os.nice(10)
    return kw


def which(binary: str) -> str | None:
    if os.path.isfile(binary):
        return binary
    return shutil.which(binary)


def run(args: Sequence[str], low_priority: bool = True, timeout: float | None = None,
        cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    log.debug("run: %s", " ".join(map(str, args)))
    proc = subprocess.run(list(map(str, args)), capture_output=True, timeout=timeout,
                          cwd=cwd, **popen_kwargs(low_priority))
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-6:]
        raise RuntimeError(f"{Path(str(args[0])).name} failed: " + " | ".join(tail))
    return proc


@lru_cache(maxsize=4)
def version(ffmpeg: str) -> str | None:
    path = which(ffmpeg)
    if not path:
        return None
    try:
        out = subprocess.run([path, "-hide_banner", "-version"], capture_output=True,
                             timeout=10, **popen_kwargs(False)).stdout.decode(errors="replace")
        return out.split("\n", 1)[0].replace("ffmpeg version ", "").split(" ")[0]
    except Exception:
        return None


@lru_cache(maxsize=4)
def detect_encoder(ffmpeg: str, preferred: str = "auto") -> str:
    """Pick a hardware H.264 encoder that actually works on this machine, else libx264."""
    if preferred and preferred != "auto":
        return preferred
    path = which(ffmpeg)
    if not path:
        return "libx264"
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"):
        try:
            # Encoders can be *compiled in* without the GPU being present, so test-encode 1 frame.
            r = subprocess.run([path, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                "-i", "color=black:s=256x256:d=0.1", "-frames:v", "1",
                                "-c:v", enc, "-f", "null", "-"],
                               capture_output=True, timeout=15, **popen_kwargs(True))
            if r.returncode == 0:
                return enc
        except Exception:
            continue
    return "libx264"


def encoder_args(encoder: str, threads: int = 2) -> list[str]:
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-threads", str(threads)]
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "21", "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "22"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "21", "-qp_p", "23"]
    return ["-c:v", encoder]


def probe(ffprobe: str, path: str | Path) -> dict:
    proc = run([ffprobe, "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", str(path)], low_priority=False, timeout=60)
    return json.loads(proc.stdout or b"{}")


def duration(ffprobe: str, path: str | Path) -> float:
    try:
        return float(probe(ffprobe, path).get("format", {}).get("duration", 0) or 0)
    except Exception:
        return 0.0


def video_size(ffprobe: str, path: str | Path) -> tuple[int, int]:
    for s in probe(ffprobe, path).get("streams", []):
        if s.get("codec_type") == "video":
            return int(s.get("width", 0)), int(s.get("height", 0))
    return 0, 0


def has_audio(ffprobe: str, path: str | Path) -> bool:
    try:
        return any(s.get("codec_type") == "audio" for s in probe(ffprobe, path).get("streams", []))
    except Exception:
        return False


def thumbnail(ffmpeg: str, src: Path, dst: Path, at: float = 1.0) -> Path:
    run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", src,
         "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", dst], timeout=60)
    return dst
