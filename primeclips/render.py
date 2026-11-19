"""9:16 renderer for Shorts / Reels / TikTok.

Layouts
  vertical-blur : full frame centred over a blurred, zoomed copy of itself (safe for anything)
  streamer      : facecam centred on top + 3:4 gameplay below, over a dark blurred backdrop
  gaming        : facecam on top, gameplay below, edge to edge (classic streamer-clip stack)
  crop          : hard centre crop to 9:16 (action / face in the middle)
  landscape     : keep 16:9 (only re-encoded if captions are burned in)

The blur is done at quarter resolution and scaled up: same look, ~10x cheaper.
Video and audio timestamps are reset to zero on every render, so clips cut from DASH
or HLS sources never drift out of sync."""
from __future__ import annotations

import os
from pathlib import Path

from .config import Config
from .ffmpeg import detect_encoder, encoder_args, run, which

W, H = 1080, 1920


def _facecam() -> tuple[float, float, float, float]:
    """Facecam rectangle as fractions of the source frame: x,y,w,h (env PRIMECLIPS_FACECAM)."""
    try:
        x, y, w, h = (float(v) for v in os.environ.get("PRIMECLIPS_FACECAM", "0,0,0.28,0.30").split(","))
        return x, y, w, h
    except ValueError:
        return 0.0, 0.0, 0.28, 0.30


def caption_anchor(layout: str) -> tuple[int, int, int, int]:
    """(play_res_x, play_res_y, x, y) where captions sit for a layout: in the open space
    just below the facecam seam, or in the lower third. Never over the bottom UI buttons."""
    return {"streamer": (W, H, W // 2, 825), "gaming": (W, H, W // 2, 760),
            "landscape": (1920, 1080, 960, 900)}.get(layout, (W, H, W // 2, 1340))


def filter_graph(layout: str, ass: str | None = None) -> str:
    if layout == "streamer":
        fx, fy, fw, fh = _facecam()
        cam_w, cam_h, game_h = 620, 400, 1440
        g = ("[0:v]split=3[a][b][c];"
             f"[a]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
             f"boxblur=10:2,scale={W}:{H},eq=brightness=-0.15,setsar=1[bg];"
             f"[b]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={cam_w}:{cam_h}:force_original_aspect_ratio=increase,"
             f"crop={cam_w}:{cam_h},setsar=1[cam];"
             "[c]crop='min(iw,ih*3/4)':ih:'(iw-min(iw,ih*3/4))/2':0,"
             f"scale={W}:{game_h},setsar=1[game];"
             f"[bg][game]overlay=0:{cam_h}[t];[t][cam]overlay=(W-w)/2:0[v]")
    elif layout == "crop":
        g = ("[0:v]crop='min(iw,ih*9/16)':ih:'(iw-min(iw,ih*9/16))/2':0,"
             f"scale={W}:{H},setsar=1[v]")
    elif layout == "gaming":
        fx, fy, fw, fh = _facecam()
        cam_h = 640
        game_h = H - cam_h
        g = ("[0:v]split=2[a][b];"
             f"[a]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={W}:{cam_h}:force_original_aspect_ratio=increase,"
             f"crop={W}:{cam_h},setsar=1[cam];"
             f"[b]crop='min(iw,ih*{W}/{game_h})':ih:'(iw-min(iw,ih*{W}/{game_h}))/2':0,"
             f"scale={W}:{game_h},setsar=1[game];"
             "[cam][game]vstack=inputs=2[v]")
    elif layout == "landscape":
        g = "[0:v]scale='min(1920,iw)':-2,setsar=1[v]"
    else:  # vertical-blur
        g = ("[0:v]split=2[a][b];"
             f"[a]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
             f"boxblur=6:2,scale={W}:{H},eq=brightness=-0.08,setsar=1[bg];"
             f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
             "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
    fps = os.environ.get("PRIMECLIPS_RENDER_FPS", "30")
    tail = f"fps={fps}" if fps and fps != "source" else "null"
    if ass:
        tail += f",subtitles=f={ass}"
    g = "[0:v]setpts=PTS-STARTPTS[src];" + g.replace("[0:v]", "[src]")
    return g.replace("[v]", "[v0]") + f";[v0]{tail},format=yuv420p[v]"


# zero-based audio timestamps (no drift vs. video) + loudness at the -14 LUFS that
# Shorts / Reels / TikTok normalise to, so clips aren't quieter than the next video
AUDIO_SYNC = ("asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0,"
              "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000")


def render(cfg: Config, src: Path, dst: Path, layout: str, ass: Path | None = None) -> Path:
    """Render src into dst. `ass` must live in the same folder as dst (we run ffmpeg
    there so the subtitles filter gets a plain relative path; Windows paths with drive
    colons are a notorious escaping nightmare in filtergraphs)."""
    encoder = detect_encoder(cfg.ffmpeg, cfg.encoder)
    graph = filter_graph(layout, ass.name if ass else None)

    def args(enc: str) -> list[str]:
        return [which(cfg.ffmpeg) or cfg.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src.resolve()), "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
                *encoder_args(enc, cfg.threads), "-af", AUDIO_SYNC, "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", dst.name]

    try:
        run(args(encoder), low_priority=cfg.low_priority, timeout=900, cwd=dst.parent)
    except RuntimeError:
        if encoder == "libx264":
            raise
        # GPU encoder hiccup (driver busy, session limit): fall back to CPU once.
        run(args("libx264"), low_priority=cfg.low_priority, timeout=900, cwd=dst.parent)
    return dst
