"""The engine: live sessions, the clip library, the render worker and the event bus.
Used by both the web server and the CLI."""
from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__, ai, audio, captions, ffmpeg, ingest, publish
from .buffer import ReplayBuffer, Segment
from .chat import start_chat
from .config import LAYOUTS, Config, SessionSettings
from .detector import HypeDetector
from .render import render

log = logging.getLogger("primeclips")


def _id(n: int = 6) -> str:
    return uuid.uuid4().hex[:n]


# ============================================================================ events
class EventBus:
    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def emit(self, type_: str, **data) -> None:
        msg = {"type": type_, **data}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


class _BusLogHandler(logging.Handler):
    def __init__(self, bus: EventBus):
        super().__init__(logging.INFO)
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        level = {logging.WARNING: "warn", logging.ERROR: "error"}.get(record.levelno, "info")
        self.bus.emit("log", level=level, message=record.getMessage())


# ============================================================================ clips
@dataclass
class Clip:
    id: str
    title: str
    kind: str                      # live | manual | vod
    source_url: str
    channel: str
    reason: str
    score: float
    start: float
    end: float
    layout: str
    session_id: str | None = None
    captions: bool = False
    created_at: float = field(default_factory=time.time)
    status: str = "queued"
    error: str | None = None
    published: dict = field(default_factory=lambda: {"discord": False, "youtube": None})

    def path(self, cfg: Config, name: str) -> Path:
        return cfg.clips_dir / self.id / {"raw": "raw.mp4", "vertical": "vertical.mp4",
                                           "thumb": "thumb.jpg", "ass": "captions.ass"}.get(name, name)

    def to_api(self, cfg: Config) -> dict:
        d = asdict(self)
        d["duration"] = round(self.end - self.start, 2)
        d["files"] = {k: (f"/api/clips/{self.id}/file/{k}" if self.path(cfg, k).exists() else None)
                      for k in ("raw", "vertical", "thumb")}
        return d


class Library:
    def __init__(self, cfg: Config, bus: EventBus):
        self.cfg, self.bus = cfg, bus
        self._clips: dict[str, Clip] = {}
        self._lock = threading.Lock()
        for meta in cfg.clips_dir.glob("*/meta.json"):
            try:
                c = Clip(**json.loads(meta.read_text(encoding="utf-8")))
                if c.status not in ("ready", "error"):
                    c.status, c.error = "error", "interrupted (app restarted)"
                self._clips[c.id] = c
            except Exception:
                log.debug("skipping unreadable %s", meta)

    def new(self, **kw) -> Clip:
        clip = Clip(id=_id(8), **kw)
        (self.cfg.clips_dir / clip.id).mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._clips[clip.id] = clip
        self.save(clip)
        return clip

    def save(self, clip: Clip, **changes) -> Clip:
        for k, v in changes.items():
            setattr(clip, k, v)
        p = self.cfg.clips_dir / clip.id / "meta.json"
        if p.parent.exists():
            p.write_text(json.dumps(asdict(clip), ensure_ascii=False, indent=1), encoding="utf-8")
        self.bus.emit("clip", clip=clip.to_api(self.cfg))
        return clip

    def get(self, cid: str) -> Clip | None:
        return self._clips.get(cid)

    def all(self) -> list[Clip]:
        with self._lock:
            return sorted(self._clips.values(), key=lambda c: c.created_at, reverse=True)

    def delete(self, cid: str) -> bool:
        with self._lock:
            clip = self._clips.pop(cid, None)
        if clip:
            shutil.rmtree(self.cfg.clips_dir / cid, ignore_errors=True)
        return clip is not None


class Worker(threading.Thread):
    """ONE render at a time, on purpose: keeps the CPU/GPU free for the game and the
    stream. Cuts (stream copy) never wait in this queue; only re-encodes do."""

    def __init__(self) -> None:
        super().__init__(daemon=True, name="render-worker")
        self.q: queue.Queue[Callable[[], None]] = queue.Queue()

    def submit(self, fn: Callable[[], None]) -> None:
        self.q.put(fn)

    def run(self) -> None:
        while True:
            fn = self.q.get()
            try:
                fn()
            except Exception:
                log.exception("render job crashed")


# ============================================================================ live session
class LiveSession:
    def __init__(self, app: "App", url: str, settings: SessionSettings):
        self.app = app
        self.id = _id()
        self.url = url
        self.platform, self.channel = ingest.detect(url)
        self.settings = settings
        self.state = "starting"
        self.error: str | None = None
        self.started_at = time.time()
        self.detector = HypeDetector(settings.threshold, settings.cooldown)
        self.history: deque = deque(maxlen=180)
        self.chat_log: deque = deque(maxlen=50)
        self._chat_batch: list = []
        self._chat_lock = threading.Lock()
        self.clips = 0
        self.buffer: ReplayBuffer | None = None
        self.chat = None
        self._stop = threading.Event()

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name=f"live-{self.id}").start()

    def _run(self) -> None:
        try:
            source = ingest.resolve(self.url, self.app.cfg.stream_quality)
            self.buffer = ReplayBuffer(self.app.cfg, source, self.app.cfg.buffers_dir / self.id,
                                       on_segment=self._on_segment, on_exit=self._on_exit)
            self.buffer.start()
            if self.settings.chat:
                self.chat = start_chat(self.platform, self.channel, self.url, self._on_chat)
            log.info("watching %s (%s)", self.channel, self.platform)
        except Exception as e:
            self._fail(str(e))
            return
        while not self._stop.wait(1.0):
            self._tick()

    def _fail(self, msg: str) -> None:
        self.state, self.error = "error", msg
        log.error("session %s: %s", self.channel, msg)
        self.app.bus.emit("session", session=self.to_api())

    def _on_exit(self, reason: str | None) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self.state != "live" or (reason and reason != "stream ended"):
            self._fail(reason or "stream stopped")
        else:
            self.state = "stopped"
            log.info("%s: stream ended", self.channel)
            self.app.bus.emit("session", session=self.to_api())
        if self.chat:
            self.chat.stop()

    def stop(self) -> None:
        if self.state in ("stopped", "error"):
            return
        self.state = "stopping"
        self.app.bus.emit("session", session=self.to_api())
        self._stop.set()
        if self.chat:
            self.chat.stop()
        if self.buffer:
            self.buffer.stop()
        self.state = "stopped"
        self.app.bus.emit("session", session=self.to_api())

    # --------------------------------------------------------------- signals
    def _on_segment(self, seg: Segment) -> None:
        if self.state == "starting":
            self.state = "live"
            self.app.bus.emit("session", session=self.to_api())
        for i, db in enumerate(audio.segment_levels(self.app.cfg.ffmpeg, seg.path, 0.5)):
            self.detector.add_audio(seg.start + i * 0.5, db)

    def _on_chat(self, user: str, text: str) -> None:
        if self.buffer:
            self.detector.add_chat(self.buffer.now(), text)
        msg = {"user": user, "text": text[:300], "t": time.time()}
        with self._chat_lock:
            self.chat_log.append(msg)
            self._chat_batch.append(msg)

    def _tick(self) -> None:
        if not self.buffer or self.state != "live":
            return
        now = self.buffer.now()
        score, reason = self.detector.tick(now)
        st = self.detector.last
        point = {"t": time.time(), "score": score, "audio_db": st["audio_db"], "chat_rate": st["chat_rate"]}
        self.history.append(point)
        self.app.bus.emit("tick", session_id=self.id, buffer_seconds=round(self.buffer.seconds, 1), **point)
        with self._chat_lock:
            batch, self._chat_batch = self._chat_batch[-40:], []
        if batch:
            self.app.bus.emit("chat", session_id=self.id, messages=batch)
        if reason and self.settings.auto_clip:
            log.info("🔥 %s: auto clip (%s, score %.0f)", self.channel, reason, score)
            self.app.clip_live(self, now - self.settings.pre, now + self.settings.post,
                               kind="live", reason=reason, score=score)

    def to_api(self, full: bool = False) -> dict:
        d = {"id": self.id, "url": self.url, "platform": self.platform, "channel": self.channel,
             "state": self.state, "error": self.error, "started_at": self.started_at,
             "buffer_seconds": round(self.buffer.seconds, 1) if self.buffer else 0.0,
             "settings": self.settings.to_dict(),
             "stats": {**self.detector.last, "clips": self.clips}}
        if full:
            d["history"] = list(self.history)
            with self._chat_lock:
                d["chat"] = list(self.chat_log)
        return d


# ============================================================================ app
class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.bus = EventBus()
        logging.getLogger("primeclips").addHandler(_BusLogHandler(self.bus))
        self.library = Library(cfg, self.bus)
        self.worker = Worker()
        self.worker.start()
        self.sessions: dict[str, LiveSession] = {}
        self.jobs: dict[str, dict] = {}

    # --------------------------------------------------------------- status
    def capabilities(self) -> dict:
        ff = ffmpeg.version(self.cfg.ffmpeg)
        return {"ffmpeg": bool(ff), "ffmpeg_version": ff or "",
                "streamlink": bool(ingest.streamlink_cmd()), "ytdlp": bool(ingest.ytdlp_cmd()),
                "whisper": captions.available(), "llm": ai.enabled(self.cfg),
                "discord": bool(self.cfg.discord_webhook), "youtube": bool(self.cfg.youtube_secrets),
                "encoder": ffmpeg.detect_encoder(self.cfg.ffmpeg, self.cfg.encoder) if ff else ""}

    def status(self) -> dict:
        return {"version": __version__, "capabilities": self.capabilities(),
                "defaults": {**self.cfg.defaults.to_dict(), "layouts": LAYOUTS},
                "sessions": [s.to_api() for s in self.sessions.values()],
                "jobs": list(self.jobs.values())}

    # --------------------------------------------------------------- live
    def start_live(self, url: str, overrides: dict | None = None) -> LiveSession:
        settings = SessionSettings(**self.cfg.defaults.to_dict()).update(overrides or {})
        s = LiveSession(self, url, settings)
        self.sessions[s.id] = s
        s.start()
        self.bus.emit("session", session=s.to_api())
        return s

    def latest_session(self) -> LiveSession | None:
        live = [s for s in self.sessions.values() if s.state == "live"]
        return max(live, key=lambda s: s.started_at) if live else None

    def manual_clip(self, s: LiveSession, seconds: float = 30, layout: str | None = None) -> Clip:
        if not s.buffer or s.state != "live":
            raise RuntimeError("session is not live yet")
        now = s.buffer.now() + 0.5  # include the moment the button was hit
        return self.clip_live(s, now - float(seconds), now, kind="manual", reason="manual clip",
                              score=s.detector.last["score"], layout=layout)

    def clip_live(self, s: LiveSession, t0: float, t1: float, kind: str, reason: str,
                  score: float, layout: str | None = None) -> Clip:
        t0 = max(t0, s.buffer.earliest)
        clip = self.library.new(title=self.cfg.title_template.format(channel=s.channel, reason=reason),
                                kind=kind, source_url=s.url, channel=s.channel, reason=reason,
                                score=score, start=t0, end=t1, layout=layout or s.settings.layout,
                                session_id=s.id, captions=s.settings.captions)
        s.clips += 1
        s.buffer.pin(clip.id, t0)

        def cut() -> None:
            try:
                self.library.save(clip, status="cutting")
                s.buffer.wait_until(t1, timeout=(t1 - s.buffer.now()) + 20)
                start, end = s.buffer.cut(t0, t1, clip.path(self.cfg, "raw"))
                self.library.save(clip, start=start, end=end)
                self.worker.submit(lambda: self.finish(clip))
            except Exception as e:
                self.library.save(clip, status="error", error=str(e))
            finally:
                s.buffer.unpin(clip.id)

        threading.Thread(target=cut, daemon=True).start()
        return clip

    # --------------------------------------------------------------- post-processing
    def finish(self, clip: Clip) -> None:
        """thumbnail -> captions -> 9:16 render -> AI title -> notify. Each step is optional
        and failures degrade gracefully: you always keep at least the raw clip."""
        cfg = self.cfg
        raw = clip.path(cfg, "raw")
        try:
            dur = ffmpeg.duration(cfg.ffprobe, raw) or (clip.end - clip.start)
            try:
                ffmpeg.thumbnail(cfg.ffmpeg, raw, clip.path(cfg, "thumb"), at=min(dur * 0.6, max(dur - 0.5, 0)))
            except Exception as e:
                log.debug("thumbnail failed: %s", e)
            self.library.save(clip)  # thumb is visible now
            transcript, ass = "", None
            if clip.captions and captions.available():
                self.library.save(clip, status="captioning")
                try:
                    words = captions.transcribe(raw, cfg.whisper_model, cfg.threads)
                    transcript = " ".join(w[2] for w in words)
                    if words:
                        vertical = clip.layout != "landscape"
                        ass = captions.write_ass(words, clip.path(cfg, "ass"),
                                                 *((1080, 1920) if vertical else (1920, 1080)),
                                                 margin_v=560 if vertical else 90)
                except Exception as e:
                    log.warning("captions failed, rendering without: %s", e)
            if clip.layout != "landscape" or ass:
                self.library.save(clip, status="rendering")
                render(cfg, raw, clip.path(cfg, "vertical"), clip.layout, ass)
            t = ai.title(cfg, clip.channel, clip.reason, transcript)
            self.library.save(clip, status="ready", title=t or clip.title)
            log.info("🎬 clip ready: %s", clip.title)
        except Exception as e:
            self.library.save(clip, status="error", error=str(e)[:500])
            log.error("clip %s failed: %s", clip.id, e)
            return
        if cfg.discord_auto and cfg.discord_webhook:
            try:
                self.publish(clip, "discord")
            except Exception as e:  # never un-ready a finished clip because a ping failed
                log.warning("discord auto-post failed: %s", e)

    def best_file(self, clip: Clip) -> Path:
        v = clip.path(self.cfg, "vertical")
        return v if v.exists() else clip.path(self.cfg, "raw")

    def publish(self, clip: Clip, target: str) -> Clip:
        f = self.best_file(clip)
        if target == "discord":
            publish.discord(self.cfg, f"🎬 **{clip.title}**\n{clip.source_url}\n{self.cfg.hashtags}", f)
            clip.published["discord"] = True
        elif target == "youtube":
            url = publish.youtube(self.cfg, f, clip.title,
                                  f"Clipped live from {clip.source_url}\n\n{self.cfg.hashtags}")
            clip.published["youtube"] = url
        else:
            raise ValueError("target must be discord or youtube")
        return self.library.save(clip)

    # --------------------------------------------------------------- vod
    def start_vod(self, url: str, **opts) -> dict:
        from .vod import run_vod
        job = {"id": _id(), "kind": "vod", "url": url, "status": "queued", "progress": 0.0,
               "message": "", "clip_ids": [], "error": None}
        self.jobs[job["id"]] = job
        threading.Thread(target=run_vod, args=(self, job), kwargs=opts, daemon=True).start()
        self.bus.emit("job", job=job)
        return job

    def update_job(self, job: dict, **changes) -> None:
        job.update(changes)
        self.bus.emit("job", job=job)

    def shutdown(self) -> None:
        for s in list(self.sessions.values()):
            s.stop()
