# 🎬 Example clips: 10 shorts from one command

These 10 clips were produced **automatically** by Prime Clips from a single 35-minute stream:

```bash
PRIMECLIPS_COOKIES_FROM_BROWSER=firefox PRIMECLIPS_VOD_MAX_HEIGHT=720 PRIMECLIPS_FACECAM=0,0.415,0.205,0.235 primeclips vod https://youtu.be/kR8bhkVAgBY --top 10 --layout streamer --captions --delete-source
```

- **Moments:** loudness peaks against the stream's own rolling baseline, spread across the whole video.
- **Layout:** `streamer`: facecam on top, 3:4 gameplay below, dark blurred backdrop.
- **Captions:** faster-whisper word timestamps, rendered as bold karaoke subtitles.
- **Audio:** timestamps reset to zero (no A/V drift) and loudness normalised to -14 LUFS.

Click a file to play it on GitHub. These copies are re-encoded to 720×1280 to keep the repo light; Prime Clips itself outputs 1080×1920.

| # | Clip | Moment in source | Hype score | Why it was picked |
|---|---|---|---|---|
| 1 | [▶️ 01_SpeedUniverse_02m07s.mp4](01_SpeedUniverse_02m07s.mp4) | [2:07 → 2:39](https://youtu.be/kR8bhkVAgBY?t=127) | 82 | audio peak |
| 2 | [▶️ 02_SpeedUniverse_07m51s.mp4](02_SpeedUniverse_07m51s.mp4) | [7:51 → 8:23](https://youtu.be/kR8bhkVAgBY?t=471) | 74 | audio peak |
| 3 | [▶️ 03_SpeedUniverse_10m32s.mp4](03_SpeedUniverse_10m32s.mp4) | [10:32 → 11:04](https://youtu.be/kR8bhkVAgBY?t=632) | 70 | audio peak |
| 4 | [▶️ 04_SpeedUniverse_15m29s.mp4](04_SpeedUniverse_15m29s.mp4) | [15:29 → 16:01](https://youtu.be/kR8bhkVAgBY?t=929) | 71 | audio peak |
| 5 | [▶️ 05_SpeedUniverse_19m12s.mp4](05_SpeedUniverse_19m12s.mp4) | [19:12 → 19:44](https://youtu.be/kR8bhkVAgBY?t=1152) | 76 | audio peak |
| 6 | [▶️ 06_SpeedUniverse_22m42s.mp4](06_SpeedUniverse_22m42s.mp4) | [22:42 → 23:14](https://youtu.be/kR8bhkVAgBY?t=1362) | 72 | audio peak |
| 7 | [▶️ 07_SpeedUniverse_25m21s.mp4](07_SpeedUniverse_25m21s.mp4) | [25:21 → 25:53](https://youtu.be/kR8bhkVAgBY?t=1521) | 82 | audio peak |
| 8 | [▶️ 08_SpeedUniverse_28m07s.mp4](08_SpeedUniverse_28m07s.mp4) | [28:07 → 28:39](https://youtu.be/kR8bhkVAgBY?t=1687) | 80 | audio peak |
| 9 | [▶️ 09_SpeedUniverse_31m20s.mp4](09_SpeedUniverse_31m20s.mp4) | [31:20 → 31:52](https://youtu.be/kR8bhkVAgBY?t=1880) | 74 | audio peak |
| 10 | [▶️ 10_SpeedUniverse_33m31s.mp4](10_SpeedUniverse_33m31s.mp4) | [33:31 → 34:03](https://youtu.be/kR8bhkVAgBY?t=2011) | 71 | audio peak |

Source: [iShowSpeed's First Time Playing GTA 6! (SpeedUniverse)](https://youtu.be/kR8bhkVAgBY), used to demo the clipping pipeline.
