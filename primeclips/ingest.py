"""Resolve any stream URL into something ffmpeg can read.

Order of preference:
  1. local file / rtmp / srt / direct .m3u8   -> ffmpeg reads it directly
  2. streamlink (best for Twitch & Kick: low-latency HLS, ad handling) -> piped into ffmpeg
  3. yt-dlp -g (YouTube Live, and ~1800 other sites) -> ffmpeg reads the HLS URL
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .ffmpeg import popen_kwargs, which

DIRECT_SCHEMES = ("rtmp", "rtmps", "srt", "udp", "rtsp", "tcp")


@dataclass
class Source:
    url: str
    platform: str
    channel: str
    input_args: list[str] = field(default_factory=list)  # ffmpeg args before output
    upstream: list[str] | None = None                    # command whose stdout feeds ffmpeg
    is_file: bool = False


def detect(url: str) -> tuple[str, str]:
    """Return (platform, channel) from a URL. Best effort, never raises."""
    if is_local(url):
        return "file", Path(url).stem
    u = urlparse(url if "://" in url else "https://" + url)
    host = (u.netloc or "").lower().removeprefix("www.").removeprefix("m.")
    parts = [p for p in u.path.split("/") if p]
    if host.endswith("twitch.tv"):
        return "twitch", (parts[0] if parts else "twitch").lower()
    if host.endswith("kick.com"):
        return "kick", (parts[0] if parts else "kick").lower()
    if host.endswith("youtube.com") or host == "youtu.be":
        if parts and parts[0].startswith("@"):
            return "youtube", parts[0][1:]
        if len(parts) >= 2 and parts[0] in ("c", "channel", "user"):
            return "youtube", parts[1]
        return "youtube", "youtube"
    return (u.scheme if u.scheme in DIRECT_SCHEMES else host.split(".")[0] or "stream"), (parts[-1] if parts else host)


def is_local(url: str) -> bool:
    return not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I) and Path(url).exists()


def _module_cmd(binary: str, module: str) -> list[str] | None:
    path = which(binary)
    if path:
        return [path]
    if importlib.util.find_spec(module) is not None:
        return [sys.executable, "-m", module]
    return None


def streamlink_cmd() -> list[str] | None:
    return _module_cmd("streamlink", "streamlink")


def ytdlp_cmd() -> list[str] | None:
    return _module_cmd("yt-dlp", "yt_dlp")


def resolve(url: str, quality: str = "best", realtime_file: bool = True) -> Source:
    url = url.strip()
    platform, channel = detect(url)
    src = Source(url=url, platform=platform, channel=channel)

    if is_local(url):
        src.is_file = True
        # -re makes a file behave like a live stream: perfect for demos and testing.
        src.input_args = (["-re"] if realtime_file else []) + ["-i", str(Path(url).resolve())]
        return src

    scheme = urlparse(url).scheme.lower()
    if scheme in DIRECT_SCHEMES or url.split("?")[0].endswith(".m3u8"):
        src.input_args = ["-i", url]
        return src

    sl = streamlink_cmd()
    if sl and platform in ("twitch", "kick", "youtube"):
        extra = ["--twitch-low-latency"] if platform == "twitch" else []
        src.upstream = sl + ["--stdout", "--loglevel", "warning", "--hls-live-edge", "2",
                             *extra, url, f"{quality},best"]
        src.input_args = ["-i", "pipe:0"]
        return src

    yd = ytdlp_cmd()
    if yd:
        fmt = "best[height<=1080]/best" if quality == "best" else quality
        out = subprocess.run(yd + ["-g", "-f", fmt, "--no-warnings", url], capture_output=True,
                             timeout=60, **popen_kwargs(False))
        lines = [l for l in out.stdout.decode(errors="replace").splitlines() if l.startswith("http")]
        if not lines:
            err = out.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no stream URL"]
            raise RuntimeError(f"yt-dlp could not resolve the stream: {err[0]}")
        src.input_args = []
        for line in lines[:2]:  # 1 muxed URL, or separate video + audio
            src.input_args += ["-i", line]
        return src

    if sl:
        src.upstream = sl + ["--stdout", "--loglevel", "warning", url, f"{quality},best"]
        src.input_args = ["-i", "pipe:0"]
        return src

    raise RuntimeError("Install streamlink or yt-dlp to clip online streams: pip install streamlink yt-dlp")
