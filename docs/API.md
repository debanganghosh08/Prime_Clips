# Prime Clips HTTP API

Base URL: `http://localhost:8765` (change with `--port`). All bodies are JSON.

## Objects

**Session** (a live stream being watched)
```json
{
  "id": "a1b2c3", "url": "https://twitch.tv/somestreamer", "platform": "twitch",
  "channel": "somestreamer",
  "state": "starting | live | stopping | stopped | error", "error": null,
  "started_at": 1763540000.0, "buffer_seconds": 184.0,
  "settings": {"layout": "gaming", "auto_clip": true, "threshold": 70,
               "pre": 25, "post": 8, "chat": true, "captions": false},
  "stats": {"score": 42.5, "audio_db": -18.2, "chat_rate": 3.4, "clips": 2}
}
```

**Clip**
```json
{
  "id": "k9x8", "title": "somestreamer loses it 😱", "kind": "live | manual | vod",
  "session_id": "a1b2c3", "source_url": "https://twitch.tv/somestreamer",
  "reason": "chat spike + audio peak", "score": 88.1,
  "start": 120.0, "end": 153.0, "duration": 33.0, "created_at": 1763540100.0,
  "layout": "gaming",
  "status": "queued | cutting | rendering | captioning | ready | error", "error": null,
  "files": {"raw": "/api/clips/k9x8/file/raw", "vertical": "/api/clips/k9x8/file/vertical",
            "thumb": "/api/clips/k9x8/file/thumb"},
  "published": {"discord": false, "youtube": null}
}
```
`files.*` is `null` until that file exists.

**Job** (VOD scan)
```json
{"id": "j1", "kind": "vod", "url": "...", "status": "queued | downloading | analyzing | clipping | done | error",
 "progress": 0.4, "message": "found 5 moments", "clip_ids": ["k9x8"], "error": null}
```

## Routes

| Method | Path | Body / notes | Returns |
|---|---|---|---|
| GET | `/` | dashboard | HTML |
| GET | `/api/status` | | `{version, capabilities, defaults, sessions:[Session], jobs:[Job]}` |
| POST | `/api/live/start` | `{url, layout?, auto_clip?, threshold?, pre?, post?, chat?, captions?}` | `Session` |
| GET | `/api/live/{sid}` | | `Session` + `history: [{t, score, audio_db, chat_rate}]` (last 180 ticks) + `chat: [{user, text, t}]` (last 50) |
| POST | `/api/live/{sid}/stop` | | `Session` |
| POST | `/api/live/{sid}/clip` | `{seconds?: 30, layout?}` clips the last N seconds | `Clip` |
| POST | `/api/clip` | `{seconds?: 30}` clips the most recent live session (Stream Deck / hotkey friendly) | `Clip` |
| POST | `/api/vod` | `{url, top_n?: 5, layout?, captions?, min_len?: 20, max_len?: 45, ai?: false}` url can be a local path; `ai` lets the LLM pick moments from the transcript (experimental) | `Job` |
| GET | `/api/clips` | newest first | `[Clip]` |
| GET | `/api/clips/{id}` | | `Clip` |
| GET | `/api/clips/{id}/file/{raw\|vertical\|thumb}` | supports Range for video | file |
| DELETE | `/api/clips/{id}` | | `{ok: true}` |
| POST | `/api/clips/{id}/publish` | `{target: "discord" \| "youtube"}` | `Clip` |
| GET | `/api/events` | Server-Sent Events, see below | stream |

`capabilities` = `{ffmpeg, ffmpeg_version, streamlink, ytdlp, whisper, llm, discord, youtube, encoder}` (bools, except the version and encoder strings).
`defaults` = the default session settings, same keys as `Session.settings`, plus `layouts: ["vertical-blur","crop","gaming","landscape"]`.

## Events (`/api/events`)

Each message is `data: <json>\n\n` with a `type` field:

- `tick`: `{type, session_id, t, score, audio_db, chat_rate, buffer_seconds}` sent once per second per live session
- `chat`: `{type, session_id, messages: [{user, text, t}]}`, batched once per second
- `session`: `{type, session: Session}` on any state change
- `clip`: `{type, clip: Clip}` on create or any status change
- `job`: `{type, job: Job}`
- `log`: `{type, level: "info|warn|error", message}`
