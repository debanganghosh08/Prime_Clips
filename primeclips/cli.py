"""Command line.

  primeclips serve                     # dashboard on http://localhost:8765
  primeclips live <url>                # terminal mode: Enter = clip the last 30 s, q = quit
  primeclips vod <url-or-file> --top 5 # best moments of a finished stream
  primeclips doctor                    # what's installed / what's missing
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import webbrowser

from . import __version__
from .config import LAYOUTS, load_config

BANNER = r"""
  ____       _                  ____ _ _
 |  _ \ _ __(_)_ __ ___   ___  / ___| (_)_ __  ___
 | |_) | '__| | '_ ` _ \ / _ \| |   | | | '_ \/ __|
 |  __/| |  | | | | | | |  __/| |___| | | |_) \__ \
 |_|   |_|  |_|_| |_| |_|\___| \____|_|_| .__/|___/
   clip the stream before anyone else   |_|   v{v}
"""


def _session_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--layout", choices=LAYOUTS)
    p.add_argument("--threshold", type=float, help="auto-clip hype score 0-100 (default 70)")
    p.add_argument("--pre", type=float, help="seconds before the hype moment (default 25)")
    p.add_argument("--post", type=float, help="seconds after the hype moment (default 8)")
    p.add_argument("--no-auto", action="store_true", help="manual clipping only")
    p.add_argument("--no-chat", action="store_true", help="don't read live chat")
    p.add_argument("--captions", action="store_true", help="burn word-by-word captions (needs faster-whisper)")


def _overrides(a) -> dict:
    o = {"layout": a.layout, "threshold": a.threshold, "pre": a.pre, "post": a.post}
    if a.no_auto:
        o["auto_clip"] = False
    if a.no_chat:
        o["chat"] = False
    if a.captions:
        o["captions"] = True
    return {k: v for k, v in o.items() if v is not None}


def cmd_serve(a, cfg) -> None:
    import uvicorn
    from .server import create_app
    url = f"http://{'localhost' if a.host in ('0.0.0.0', '127.0.0.1') else a.host}:{a.port}"
    print(BANNER.format(v=__version__) + f"\n  dashboard -> {url}\n")
    if a.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(cfg), host=a.host, port=a.port, log_level="warning")


def _print_events(core, stop: threading.Event) -> None:
    q = core.bus.subscribe()
    while not stop.is_set():
        try:
            m = q.get(timeout=0.5)
        except Exception:
            continue
        t = m["type"]
        if t == "tick":
            bar = "█" * int(m["score"] / 5)
            sys.stdout.write(f"\r  hype {m['score']:5.1f} |{bar:<20}| audio {m['audio_db']:6.1f} dB  "
                             f"chat {m['chat_rate']:4.1f}/s  buffer {m['buffer_seconds']:5.0f}s ")
            sys.stdout.flush()
        elif t == "clip" and m["clip"]["status"] in ("ready", "error"):
            c = m["clip"]
            mark = "🎬" if c["status"] == "ready" else "❌"
            print(f"\n  {mark} {c['title']}  ->  {core.cfg.clips_dir / c['id']}  {c.get('error') or ''}")
        elif t == "session" and m["session"]["state"] in ("live", "error", "stopped"):
            s = m["session"]
            print(f"\n  ● {s['channel']}: {s['state']} {s.get('error') or ''}")


def cmd_live(a, cfg) -> None:
    from .core import App
    core = App(cfg)
    print(BANNER.format(v=__version__))
    s = core.start_live(a.url, _overrides(a))
    stop = threading.Event()
    threading.Thread(target=_print_events, args=(core, stop), daemon=True).start()
    print("  [Enter] clip last 30 s   [number + Enter] clip last N s   [q + Enter] quit\n")
    try:
        for line in sys.stdin:
            line = line.strip().lower()
            if line == "q":
                break
            try:
                c = core.manual_clip(s, float(line) if line else 30)
                print(f"\n  ✂️  clipping {c.end - c.start:.0f}s ...")
            except Exception as e:
                print(f"\n  ⚠️  {e}")
            if s.state in ("stopped", "error"):
                break
    except KeyboardInterrupt:
        pass
    stop.set()
    s.stop()
    print("\n  waiting for renders to finish (Ctrl+C to skip)...")
    try:
        while not core.worker.q.empty() or any(c.status not in ("ready", "error") for c in core.library.all()):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def cmd_vod(a, cfg) -> None:
    from .core import App
    core = App(cfg)
    print(BANNER.format(v=__version__))
    job = core.start_vod(a.url, top_n=a.top, layout=a.layout, captions_on=a.captions,
                         min_len=a.min_len, max_len=a.max_len, ai_pick=a.ai,
                         delete_source=a.delete_source)
    stop = threading.Event()
    threading.Thread(target=_print_events, args=(core, stop), daemon=True).start()
    last = ""
    while job["status"] not in ("done", "error"):
        if job["message"] != last:
            last = job["message"]
            print(f"  … {last}")
        time.sleep(0.5)
    if job["status"] == "error":
        print(f"  ❌ {job['error']}")
        return
    while any(core.library.get(i).status not in ("ready", "error") for i in job["clip_ids"]):
        time.sleep(0.5)
    stop.set()
    print(f"\n  ✅ {len(job['clip_ids'])} clips in {cfg.clips_dir}")


def cmd_clean(a, cfg) -> None:
    """Free disk space. Default: downloaded VODs + leftover replay buffers. Clips are kept
    unless --clips / --all is passed."""
    import shutil
    targets = [cfg.downloads_dir, cfg.buffers_dir] + ([cfg.clips_dir] if (a.clips or a.all) else [])
    freed = 0
    for d in targets:
        for p in d.glob("*"):
            freed += sum(f.stat().st_size for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file())
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    print(f"  🧹 freed {freed / 1e6:.1f} MB from: " + ", ".join(str(d) for d in targets))


def cmd_doctor(a, cfg) -> None:
    from .core import App
    caps = App(cfg).capabilities()
    print(BANNER.format(v=__version__))
    tips = {"ffmpeg": "install ffmpeg (winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg)",
            "streamlink": "pip install streamlink   (best for Twitch/Kick live)",
            "ytdlp": "pip install yt-dlp       (YouTube live + VODs)",
            "whisper": "pip install faster-whisper (captions)",
            "llm": "set PRIMECLIPS_LLM_BASE_URL + PRIMECLIPS_LLM_MODEL (AI titles)",
            "discord": "set PRIMECLIPS_DISCORD_WEBHOOK (instant clip pings)",
            "youtube": "set PRIMECLIPS_YOUTUBE_CLIENT_SECRETS (Shorts upload)"}
    for k, tip in tips.items():
        ok = caps[k]
        extra = f" {caps['ffmpeg_version']}" if k == "ffmpeg" and ok else ""
        print(f"  {'✅' if ok else '⬜'} {k:<11}{extra}" + ("" if ok else f"   -> {tip}"))
    print(f"  ⚡ encoder    {caps['encoder'] or '-'}\n  📁 data       {cfg.data_dir}")


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # emojis on Windows consoles
        except Exception:
            pass
    p = argparse.ArgumentParser(prog="primeclips", description="Real-time live stream clipper.")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("serve", help="web dashboard")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--open", action="store_true", help="open the browser")
    lp = sub.add_parser("live", help="clip a live stream from the terminal")
    lp.add_argument("url")
    _session_args(lp)
    vp = sub.add_parser("vod", help="find the best moments in a finished stream")
    vp.add_argument("url")
    vp.add_argument("--top", type=int, default=5)
    vp.add_argument("--layout", choices=LAYOUTS)
    vp.add_argument("--captions", action="store_true")
    vp.add_argument("--ai", action="store_true", help="let the LLM pick moments from the transcript")
    vp.add_argument("--min-len", type=float, default=20)
    vp.add_argument("--max-len", type=float, default=45)
    vp.add_argument("--delete-source", action="store_true",
                    help="delete the downloaded VOD once the clips are cut")
    sub.add_parser("doctor", help="check dependencies")
    cp = sub.add_parser("clean", help="delete downloaded VODs and leftover buffers (clips are kept)")
    cp.add_argument("--clips", action="store_true", help="also delete all finished clips")
    cp.add_argument("--all", action="store_true", help="downloads + buffers + clips")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("primeclips").setLevel(logging.DEBUG if a.verbose else logging.INFO)
    cfg = load_config()
    {"serve": cmd_serve, "live": cmd_live, "vod": cmd_vod, "doctor": cmd_doctor, "clean": cmd_clean}.get(
        a.cmd or "serve", cmd_serve)(a if a.cmd else p.parse_args(["serve"]), cfg)
