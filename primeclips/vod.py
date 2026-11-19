"""VOD / past-broadcast mode: give it a finished stream (URL or local file) and it
returns the top N moments as ready-to-post shorts.

Signal: loudness peaks relative to a rolling local baseline (cheap, works for any
game or language). If an LLM and faster-whisper are configured and `ai=True`, the
transcript is also sent to the LLM, and its picks are merged in first."""
from __future__ import annotations

import logging
import statistics
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from . import ai, audio, captions, ffmpeg, ingest
from .ffmpeg import popen_kwargs, which

if TYPE_CHECKING:
    from .core import App

log = logging.getLogger("primeclips.vod")


def download(app: "App", url: str) -> Path:
    yd = ingest.ytdlp_cmd()
    if not yd:
        raise RuntimeError("pip install yt-dlp to download VODs")
    out = subprocess.run(yd + ["-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
                               "--no-warnings", "--no-playlist", "-o",
                               str(app.cfg.downloads_dir / "%(id)s.%(ext)s"),
                               "--print", "after_move:filepath", url],
                         capture_output=True, timeout=6 * 3600, **popen_kwargs(app.cfg.low_priority))
    paths = [l for l in out.stdout.decode(errors="replace").splitlines() if l.strip()]
    if out.returncode != 0 or not paths or not Path(paths[-1]).exists():
        raise RuntimeError("download failed: " + out.stderr.decode(errors="replace").strip()[-300:])
    return Path(paths[-1])


def loudness_moments(levels: list[float], n: int, length: float) -> list[tuple[float, float]]:
    """Return [(peak_time, z_score)], the n strongest loudness peaks spaced >= length apart."""
    if len(levels) < 10:
        return []
    k = 3  # 3 s smoothing
    sm = [statistics.fmean(levels[max(0, i - k + 1):i + 1]) for i in range(len(levels))]
    std = max(statistics.pstdev(sm), 2.0)
    scored = []
    w = 60
    for i in range(len(sm)):
        lo, hi = max(0, i - w), min(len(sm), i + w)
        local = statistics.fmean(sm[lo:hi])
        scored.append(((sm[i] - local) / std + 0.35 * (sm[i] - statistics.fmean(sm)) / std, i))
    scored.sort(reverse=True)
    picks: list[tuple[float, float]] = []
    for z, i in scored:
        if all(abs(i - p) >= length for p, _ in picks):
            picks.append((float(i), z))
        if len(picks) >= n:
            break
    return picks


def run_vod(app: "App", job: dict, top_n: int = 5, layout: str | None = None, captions_on: bool = False,
            min_len: float = 20, max_len: float = 45, ai_pick: bool = False) -> None:
    cfg = app.cfg
    url = job["url"]
    try:
        if ingest.is_local(url):
            path = Path(url).resolve()
        else:
            app.update_job(job, status="downloading", progress=0.05, message="downloading VOD")
            path = download(app, url)
        platform, channel = ingest.detect(url)
        total = ffmpeg.duration(cfg.ffprobe, path)
        length = (min_len + max_len) / 2

        app.update_job(job, status="analyzing", progress=0.3, message="listening for hype moments")
        levels = [db for _, db in audio.file_levels(cfg.ffmpeg, path, 1.0)]
        moments: list[dict] = []
        if ai_pick and ai.enabled(cfg) and captions.available():
            app.update_job(job, message="transcribing + asking the LLM")
            words = captions.transcribe(path, cfg.whisper_model, cfg.threads)
            segs, cur = [], []
            for w in words:  # ~10 s transcript chunks
                cur.append(w)
                if w[1] - cur[0][0] > 10:
                    segs.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
                    cur = []
            if cur:
                segs.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
            for m in ai.pick_moments(cfg, segs, top_n, min_len, max_len):
                moments.append({**m, "reason": "AI pick"})
        for peak, z in loudness_moments(levels, top_n * 2, length):
            if len(moments) >= top_n:
                break
            s = max(0.0, peak - length * 0.7)
            if any(abs(s - m["start"]) < length for m in moments):
                continue
            moments.append({"start": s, "end": min(total or s + length, s + length), "title": "",
                            "score": round(min(99.0, 50 + z * 12), 1), "reason": "audio peak"})

        app.update_job(job, status="clipping", progress=0.5, message=f"found {len(moments)} moments")
        for i, m in enumerate(moments):
            clip = app.library.new(title=m["title"] or cfg.title_template.format(channel=channel, reason=m["reason"]),
                                   kind="vod", source_url=url, channel=channel, reason=m["reason"],
                                   score=m["score"], start=m["start"], end=m["end"],
                                   layout=layout or cfg.defaults.layout, captions=captions_on)
            app.library.save(clip, status="cutting")
            ffmpeg.run([which(cfg.ffmpeg) or cfg.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{m['start']:.2f}", "-i", str(path), "-t", f"{m['end'] - m['start']:.2f}",
                        "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy", "-avoid_negative_ts", "make_zero",
                        "-movflags", "+faststart", clip.path(cfg, "raw")], timeout=300)
            app.worker.submit(lambda c=clip: app.finish(c))
            job["clip_ids"].append(clip.id)
            app.update_job(job, progress=0.5 + 0.5 * (i + 1) / max(1, len(moments)))
        app.update_job(job, status="done", progress=1.0,
                       message=f"{len(moments)} clips queued for rendering")
    except Exception as e:
        log.error("VOD job failed: %s", e)
        app.update_job(job, status="error", error=str(e)[:500], message="failed")
