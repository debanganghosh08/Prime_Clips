# 🤖 Using Prime Clips with your AI assistant

Works with Claude Code, Antigravity, Cursor, Copilot, ChatGPT, or any coding agent.

**How to use this file:** tell your assistant *"Read `prompt.md` first and treat it as the source of truth for this repo"*, then paste one of the prompts below. Agents with file access (Claude Code, Antigravity, Cursor) can read the repo directly. For a chat-only AI, paste this whole file plus the files it asks for.

---

## 📘 Project brief (source of truth)

**Prime Clips** is a real-time clipper for live streams (Twitch, Kick, YouTube, RTMP/SRT, local files). It keeps a rolling replay buffer, scores "hype" every second, and cuts + renders 9:16 shorts within seconds. Python 3.10+, FFmpeg, FastAPI, and a vanilla-JS dashboard. No build step.

### Pipeline
```
URL ─► ingest.py (streamlink / yt-dlp / direct) ─► buffer.py (ffmpeg -c copy → 2 s .ts segments, rolling window)
                                                       │
            audio.py (per-segment loudness) ──┐        │
            chat.py  (Twitch IRC / YouTube) ──┴► detector.py (0-100 hype score) ─► core.py: clip_live()
                                                                                       │
                       buffer.cut() (stream copy, instant) ─► Worker (ONE render at a time)
                                                                │
                       captions.py (faster-whisper) → render.py (9:16 layouts) → ai.py (title) → publish.py
```

### File map
| File | Responsibility |
|---|---|
| `primeclips/config.py` | Every setting, read from `PRIMECLIPS_*` env vars / `.env`. `SessionSettings` = per-stream options. |
| `primeclips/ingest.py` | Detects platform/channel and resolves a URL into ffmpeg input args. YouTube cookies, JS-runtime handling, readable yt-dlp errors. |
| `primeclips/buffer.py` | `ReplayBuffer`: ffmpeg segmenter, segment list, pruning, `pin()` to protect ranges being cut, `cut()` by stream copy. |
| `primeclips/audio.py` | Decodes audio at 8 kHz mono and returns dBFS per window (live segments and whole files). |
| `primeclips/chat.py` | Chat readers: anonymous Twitch IRC (stdlib), YouTube via `chat-downloader`. |
| `primeclips/detector.py` | `HypeDetector`: audio z-score + chat-rate z-score + hype-emote ratio + "clip it" asks → score, threshold, cooldown, reason. |
| `primeclips/render.py` | ffmpeg filter graphs for `vertical-blur`, `crop`, `gaming`, `landscape`; GPU encoder with CPU fallback. |
| `primeclips/captions.py` | faster-whisper word timestamps → animated ASS subtitles. |
| `primeclips/ai.py` | OpenAI-compatible chat calls (stdlib HTTP): titles, VOD moment picking. |
| `primeclips/publish.py` | Discord webhook (stdlib multipart), YouTube Shorts upload (Google API). |
| `primeclips/vod.py` | VOD mode: download, loudness peaks (+ optional LLM picks), cut, render. |
| `primeclips/core.py` | `App` (sessions, jobs, publish), `LiveSession`, `Library` (clips on disk as `meta.json`), `Worker`, `EventBus`. |
| `primeclips/server.py` | FastAPI routes + Server-Sent Events. The contract is in `docs/API.md`. |
| `primeclips/web/index.html` | The whole dashboard: one file, inline CSS + vanilla JS, no CDN. |
| `primeclips/cli.py` | `serve`, `live`, `vod`, `doctor`. |
| `tests/test_core.py` | Fast tests, no ffmpeg/network: `python -m pytest -q`. |

### Rules the code follows (keep them when changing things)
1. **Never re-encode to cut.** Cuts are stream copies of buffer segments; only the 9:16 render encodes.
2. **One render at a time** via `core.Worker`, so the streamer's/clipper's PC stays smooth.
3. **Child processes run at low priority** (`ffmpeg.popen_kwargs`). Spawn new subprocesses through it.
4. **Optional features degrade gracefully.** Missing whisper / LLM / Discord never breaks a clip; you always keep `raw.mp4`.
5. **All config is env vars** in `config.py`; document new ones in `.env.example` and the README table.
6. **The dashboard is same-origin with no CORS.** Don't add a wildcard CORS policy.
7. **Never commit secrets:** `.env`, `cookies.txt` and `data/` are git-ignored.
8. **The API contract lives in `docs/API.md`.** Update it together with `server.py` and `web/index.html`.

### Data on disk
`data/clips/<id>/` → `raw.mp4`, `vertical.mp4`, `thumb.jpg`, `captions.ass`, `meta.json` · `data/buffers/<session>/` (temporary) · `data/downloads/` (VODs)

---

## 🧰 Copy-paste prompts

### 1. First-time setup
```
Read prompt.md. Help me set up Prime Clips on my machine (OS: <Windows/macOS/Linux>).
Check Python 3.10+, ffmpeg and Node.js, create a venv, install the project with
`pip install -e .`, run `primeclips doctor`, and explain anything marked missing.
Don't change any source files.
```

### 2. Fix an error
```
Read prompt.md and docs/TROUBLESHOOTING.md. I ran:
<command>
and got:
<full error output>
Find the cause. If TROUBLESHOOTING.md covers it, walk me through that fix. If it's a
real bug, show the smallest code change, explain why, and keep the rules in prompt.md.
```

### 3. YouTube is blocking me
```
Read prompt.md and the YouTube section of docs/TROUBLESHOOTING.md. My error is:
<error>
I use <browser>. Get me working with PRIMECLIPS_COOKIES_FROM_BROWSER or
PRIMECLIPS_COOKIES_FILE, and verify with `python -m yt_dlp -F <url>`.
Never print, upload or commit my cookies.
```

### 4. Tune the hype detector for a streamer
```
Read prompt.md and primeclips/detector.py. I clip <streamer>, who is
<loud/chill, big/small chat, platform>. Auto clips are <too frequent / never fire /
late>. Suggest settings (threshold, pre, post, cooldown) first. Only if settings
can't fix it, propose a detector change with a unit test in tests/test_core.py.
```

### 5. Add a new layout
```
Read prompt.md and primeclips/render.py. Add a 9:16 layout called "<name>" that
<description, e.g. "zooms 1.3x on the centre with a blurred top and bottom bar">.
Add it to LAYOUTS in config.py, return a graph from filter_graph() that ends in
[v], extend test_filter_graphs_are_well_formed, and list it in the README.
```

### 6. Add chat support for a new platform (e.g. Kick)
```
Read prompt.md and primeclips/chat.py. Add a <platform> chat reader as a
_Reader subclass that calls on_message(user, text), reconnects with backoff, and
stops cleanly. Wire it into start_chat(). Prefer stdlib, or make any new
dependency an optional extra in pyproject.toml.
```

### 7. Add a new publish target (TikTok, Instagram, Telegram...)
```
Read prompt.md, primeclips/publish.py and App.publish() in primeclips/core.py.
Add a "<target>" publish target with its settings as PRIMECLIPS_* env vars in
config.py and .env.example, a button in primeclips/web/index.html, and an update
to docs/API.md. Failures must raise a clear RuntimeError and never mark a ready
clip as errored.
```

### 8. Make it lighter on my PC
```
Read prompt.md. My specs: <CPU / GPU / RAM>. Clipping while streaming or gaming
makes my PC <hot / laggy>. Recommend .env settings (encoder, threads, render fps,
quality, buffer minutes, captions) and explain each trade-off. No code changes
unless something is clearly wasteful.
```

### 9. Understand the codebase
```
Read prompt.md, then walk me through what happens from the moment I paste a
Twitch URL to the moment a vertical clip is ready, naming the exact functions in
order. Then tell me the 3 best places to contribute first.
```

### 10. Before you open a pull request
```
Read prompt.md. Review my changes (git diff) against the rules in prompt.md. Check:
stream-copy cutting preserved, renders still go through Worker, new subprocesses
use popen_kwargs, new settings documented, docs/API.md in sync, tests pass with
`python -m pytest -q`. List problems by severity.
```
