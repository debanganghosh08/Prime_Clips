# 🩺 Troubleshooting: the problem sheet

Hit a wall? Find your symptom below. Most fixes take one line.
Start with **`primeclips doctor`**, which shows what's installed and what's missing.

---

## 📦 Install & setup

### `primeclips` / `yt-dlp` is "not recognized"
pip installed the commands into a Scripts folder that isn't on your PATH.
- Activate the venv from the Quick start, **or**
- call the modules directly: `python -m primeclips ...` and `python -m yt_dlp ...`

### `ffmpeg` not found, or a weird old ffmpeg is used
```bash
winget install Gyan.FFmpeg      # Windows
brew install ffmpeg             # macOS
sudo apt install ffmpeg         # Linux
```
If several ffmpegs are installed (Anaconda ships its own), pin one in `.env`:
```
PRIMECLIPS_FFMPEG=C:\path\to\ffmpeg.exe
PRIMECLIPS_FFPROBE=C:\path\to\ffprobe.exe
```

### Emojis show as `\U0001f3ac` or boxes in the terminal
Cosmetic only. Use Windows Terminal or VS Code's terminal, or ignore it.

---

## 📺 YouTube

### ❌ "Sign in to confirm you're not a bot"
YouTube blocks anonymous requests depending on your IP, region and the video. Fix: let yt-dlp use **your** login.

1. Open **Firefox**, sign in to youtube.com, play any video for a few seconds, close Firefox.
2. Add to `.env` (or set it in your shell):
   ```
   PRIMECLIPS_COOKIES_FROM_BROWSER=firefox
   ```
   PowerShell: `$env:PRIMECLIPS_COOKIES_FROM_BROWSER = "firefox"`

> **Why Firefox?** On Windows, Chrome and Edge encrypt their cookies in a way yt-dlp often can't read. If you only use Chrome, install the **"Get cookies.txt LOCALLY"** extension, export the cookies while on youtube.com, and set `PRIMECLIPS_COOKIES_FILE=cookies.txt`. `cookies.txt` is git-ignored. **Never commit or share it**, because it is your login.

**Check it worked:** `python -m yt_dlp --cookies-from-browser firefox -F <video-url>` should list real formats.

### ❌ "Requested format is not available", or only `sb0..sb3` storyboard formats
YouTube's player now needs a JavaScript challenge solved before it hands out video.
- Make sure yt-dlp has its solver: `pip install -U "yt-dlp[default]"` (Prime Clips depends on it, so reinstalling the project also works).
- You need **Node.js** or **Deno** installed. Prime Clips passes `--js-runtimes node` automatically when Deno is missing.

### ❌ "No supported JavaScript runtime could be found"
Install Node.js (https://nodejs.org) or Deno (`winget install DenoLand.Deno`), then retry.

### ❌ HTTP Error 429: Too Many Requests
YouTube is rate-limiting your IP. Wait 10–30 minutes, use cookies (above), and avoid hammering retries. A different network (phone hotspot) also works.

### 🐢 VOD downloads are huge or slow
Download 720p instead of 1080p: `PRIMECLIPS_VOD_MAX_HEIGHT=720`. Shorts are 1080 px wide anyway, and 720p roughly halves the download.

### 🔄 Anything else YouTube-related
`pip install -U "yt-dlp[default]"`. YouTube changes often, and yt-dlp releases fixes within days.

---

## 🟣 Twitch / 🟢 Kick

### ❌ "No playable streams found"
The channel is offline, or the URL is wrong. Use `https://twitch.tv/<channel>` / `https://kick.com/<channel>`.

### Chat rate stays at 0
- Twitch chat is read anonymously, so no login is needed. Check that `chat` is enabled for the session.
- Kick chat isn't supported yet, so detection uses audio only there.

### Stream stutters / buffer grows slowly
Your connection can't keep up with the source quality. Set `PRIMECLIPS_QUALITY=720p` (or `480p`).

---

## 🔥 Hype detection

| Symptom | Fix |
|---|---|
| Auto-clip never fires | Lower the threshold (`--threshold 55`). The detector also needs ~30 s of warm-up before its first trigger. |
| Too many auto clips | Raise `PRIMECLIPS_THRESHOLD` (e.g. 80) or `PRIMECLIPS_COOLDOWN` (e.g. 90). |
| Clip starts too late / misses the moment | Raise `PRIMECLIPS_PRE` (chat reacts 3–10 s after the moment). |
| Clip ends too early | Raise `PRIMECLIPS_POST`. |

---

## 🎬 Rendering

### GPU encoder errors (`h264_nvenc` / `h264_qsv` / `h264_amf` failed)
Prime Clips already falls back to CPU once per clip. To force CPU always: `PRIMECLIPS_ENCODER=libx264`.

### PC gets hot / CPU is high while streaming or gaming
- Keep captions **off** for live clipping.
- `PRIMECLIPS_RENDER_FPS=30` (default) and `PRIMECLIPS_THREADS=1`
- Make sure a GPU encoder is detected (`primeclips doctor` shows the encoder).
- Cutting itself is stream copy and costs almost nothing. Only the 9:16 render uses real CPU/GPU, one clip at a time.

### `gaming` layout shows the wrong corner as the facecam
Set the facecam rectangle as fractions of the frame: `x,y,width,height`.
```
PRIMECLIPS_FACECAM=0.72,0.70,0.28,0.30   # bottom-right corner
PRIMECLIPS_FACECAM=0,0,0.28,0.30         # top-left (default)
```

### Captions don't appear
- `pip install faster-whisper`, then turn captions on per session (`--captions`).
- The first run downloads the Whisper model, so give it a minute.
- Docker/Linux: a font must exist (the Docker image installs DejaVu).

---

## 🖥️ Dashboard

| Symptom | Fix |
|---|---|
| Port 8765 already in use | `primeclips serve --port 8800` |
| Page loads but nothing updates | Check the "connected" dot (top right). Restart `primeclips serve`. |
| Want it on your phone on the same Wi-Fi | `primeclips serve --host 0.0.0.0`. Trusted networks only, since the dashboard has no login. |

---

## 📣 Publishing

| Symptom | Fix |
|---|---|
| Discord message arrives without the video | Files over 24 MB are sent as text only (Discord's limit). Use a shorter clip or `PRIMECLIPS_RENDER_FPS=30`. |
| YouTube upload asks for OAuth every time | Make sure `data/youtube_token.json` is writable. Create OAuth "Desktop app" credentials in Google Cloud and point `PRIMECLIPS_YOUTUBE_CLIENT_SECRETS` at the JSON. |

---

## 💾 Disk space
- Replay buffers live in `data/buffers/` and are deleted automatically when a session stops (and on startup).
- Finished clips live in `data/clips/`. Delete them from the dashboard or the folder.
- Shrink the rolling window with `PRIMECLIPS_BUFFER_MINUTES=5`.

---

Still stuck? Open an issue with the output of `primeclips doctor` and the exact error, or paste this file plus your error into your AI assistant (see [`prompt.md`](../prompt.md)).
