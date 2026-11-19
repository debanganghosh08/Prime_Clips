"""Optional LLM layer (any OpenAI-compatible endpoint: Ollama, OpenRouter, Gemini,
OpenAI, Groq, LM Studio...). Used for scroll-stopping titles and, in VOD mode,
for picking the best moments from the transcript. Pure stdlib HTTP, no SDKs.

Examples (.env):
  PRIMECLIPS_LLM_BASE_URL=http://localhost:11434/v1          PRIMECLIPS_LLM_MODEL=llama3.2
  PRIMECLIPS_LLM_BASE_URL=https://openrouter.ai/api/v1       PRIMECLIPS_LLM_MODEL=google/gemini-2.5-flash
  PRIMECLIPS_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai  PRIMECLIPS_LLM_MODEL=gemini-2.5-flash
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request

from .config import Config

log = logging.getLogger("primeclips.ai")


def enabled(cfg: Config) -> bool:
    return bool(cfg.llm_base_url and cfg.llm_model)


def complete(cfg: Config, system: str, user: str, max_tokens: int = 400, timeout: float = 60) -> str:
    body = json.dumps({"model": cfg.llm_model, "max_tokens": max_tokens, "temperature": 0.7,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(cfg.llm_base_url.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {cfg.llm_api_key or 'none'}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"].strip()


def title(cfg: Config, channel: str, reason: str, transcript: str = "") -> str | None:
    if not enabled(cfg):
        return None
    try:
        out = complete(cfg, "You write viral YouTube Shorts / TikTok titles for gaming stream clips. "
                            "Max 60 characters, 1 emoji max, no hashtags, no quotes. Reply with the title only.",
                       f"Streamer: {channel}\nWhy it was clipped: {reason}\n"
                       f"What was said: {transcript[:1200] or '(no transcript)'}", max_tokens=40, timeout=20)
        return out.splitlines()[0].strip().strip('"')[:90] or None
    except Exception as e:
        log.warning("LLM title failed: %s", e)
        return None


def pick_moments(cfg: Config, segments: list[tuple[float, float, str]], n: int,
                 min_len: float, max_len: float) -> list[dict]:
    """Ask the LLM for the n most viral windows of a transcript. Returns
    [{start, end, title, score}]; an empty list on any failure (caller falls back to audio)."""
    if not enabled(cfg) or not segments:
        return []
    lines = "\n".join(f"[{s:.0f}-{e:.0f}] {t.strip()}" for s, e, t in segments)[:60000]
    try:
        out = complete(cfg,
                       "You are a viral short-form editor for gaming streams. Find the moments most "
                       "likely to go viral: funny, shocking, rage, clutch plays, hot takes. "
                       "Reply ONLY with JSON: [{\"start\": sec, \"end\": sec, \"title\": str, \"score\": 0-100}].",
                       f"Pick the {n} best moments, each {min_len:.0f}-{max_len:.0f} seconds long.\n"
                       f"Transcript with [start-end] seconds:\n{lines}", max_tokens=1200, timeout=120)
        m = re.search(r"\[.*\]", out, re.S)
        items = json.loads(m.group(0)) if m else []
        res = []
        for it in items:
            s, e = float(it["start"]), float(it["end"])
            if e - s < min_len:
                e = s + min_len
            res.append({"start": s, "end": min(e, s + max_len), "title": str(it.get("title", ""))[:90],
                        "score": float(it.get("score", 50))})
        return res[:n]
    except Exception as e:
        log.warning("LLM moment picking failed: %s", e)
        return []
