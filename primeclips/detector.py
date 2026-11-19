"""Hype detector. It fuses three cheap real-time signals into one 0-100 score:

  audio  : loudness now vs. the stream's own recent baseline (z-score)
  chat   : messages/second now vs. baseline (Poisson-style z-score)
  words  : share of recent messages that are hype emotes, or viewers literally typing "clip"

Everything is relative to the stream's own baseline, so a chill streamer's big moment
scores as high as a screamer's. No ML model, no GPU, microseconds per tick."""
from __future__ import annotations

import math
import re
import statistics
import threading
from collections import deque

HYPE = re.compile(
    r"\b(kekw|lul|lulw|omegalul|lmao+|lmfao|pog|pogu|poggers|pogchamp|w{3,}|holy|no ?way|wtf|"
    r"bro+|insane|clutch|clipped|monka\w*|pepelaugh|icant|sheesh|goat(ed)?|ez|gg)\b|"
    r"[😂🤣💀🔥😱😭]|\?{3,}|!{3,}", re.I)
CLIP_ASK = re.compile(r"(^|\s)!?clip( (it|that|this))?\b", re.I)


class HypeDetector:
    def __init__(self, threshold: float = 70.0, cooldown: float = 45.0, warmup: float = 30.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self.warmup = warmup
        self.audio: deque[tuple[float, float]] = deque()    # (t, dB)
        self.chat: deque[tuple[float, int, int]] = deque()  # (t, hype_hits, clip_asks)
        self.last_trigger = -1e9
        self.last = {"score": 0.0, "audio_db": -90.0, "chat_rate": 0.0}
        self._lock = threading.Lock()

    def add_audio(self, t: float, db: float) -> None:
        with self._lock:
            self.audio.append((t, db))

    def add_chat(self, t: float, text: str) -> None:
        with self._lock:
            self.chat.append((t, 1 if HYPE.search(text) else 0, 1 if CLIP_ASK.search(text) else 0))

    def _trim(self, now: float, keep: float = 180.0) -> None:
        while self.audio and self.audio[0][0] < now - keep:
            self.audio.popleft()
        while self.chat and self.chat[0][0] < now - keep:
            self.chat.popleft()

    def tick(self, now: float) -> tuple[float, str | None]:
        """Return (score, trigger_reason_or_None)."""
        with self._lock:
            self._trim(now)
            # ---- audio (the meter lags by about one segment, so look back 4 s)
            audio_z, cur_db = 0.0, self.last["audio_db"]
            recent = [db for t, db in self.audio if t >= now - 4]
            history = [db for t, db in self.audio if t < now - 4]
            if recent:
                cur_db = max(recent)
            if recent and len(history) >= 20:
                mean = statistics.fmean(history)
                std = max(statistics.pstdev(history), 3.0)
                audio_z = (cur_db - mean) / std
            # ---- chat
            win = 6.0
            now_msgs = [c for c in self.chat if c[0] >= now - win]
            old = [c for c in self.chat if c[0] < now - win]
            rate = len(now_msgs) / win
            span = max(1.0, min(170.0, now - win - (self.chat[0][0] if self.chat else now)))
            base = len(old) / span
            chat_z = (rate - base) / math.sqrt(base / win + 0.05) if (old or now_msgs) else 0.0
            hype_ratio = sum(c[1] for c in now_msgs) / max(1, len(now_msgs))
            asks = sum(c[2] for c in now_msgs)

            raw = (max(0.0, audio_z) + 0.8 * max(0.0, chat_z) +
                   2.5 * hype_ratio * min(1.0, len(now_msgs) / 5) + 0.7 * min(asks, 5))
            score = round(100 * (1 - math.exp(-raw / 3.2)), 1)
            self.last = {"score": score, "audio_db": round(cur_db, 1), "chat_rate": round(rate, 2)}

            warm = (self.audio and now - self.audio[0][0] >= self.warmup) or len(old) > 30
            if not warm or score < self.threshold or now - self.last_trigger < self.cooldown:
                return score, None
            self.last_trigger = now
            reasons = []
            if audio_z > 2:
                reasons.append("audio peak")
            if chat_z > 2:
                reasons.append("chat explosion")
            if asks >= 2:
                reasons.append("chat yelling CLIP IT")
            elif hype_ratio > 0.4 and len(now_msgs) >= 5:
                reasons.append("hype emotes")
            return score, " + ".join(reasons) or "hype spike"
