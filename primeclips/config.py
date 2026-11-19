"""Settings. Everything is driven by environment variables (or a `.env` file) so
the same build works on a laptop, a VPS, or in Docker."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

LAYOUTS = ["vertical-blur", "crop", "gaming", "landscape"]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"PRIMECLIPS_{name}", "").strip() or default


def _f(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _b(name: str, default: bool) -> bool:
    v = _env(name, "")
    return default if v == "" else v.lower() in ("1", "true", "yes", "on")


@dataclass
class SessionSettings:
    layout: str = "vertical-blur"
    auto_clip: bool = True
    threshold: float = 70.0      # hype score (0-100) that triggers an auto clip
    pre: float = 25.0            # seconds kept BEFORE the trigger (chat reacts late)
    post: float = 8.0            # seconds kept AFTER the trigger
    chat: bool = True
    captions: bool = False       # needs faster-whisper; costs CPU
    cooldown: float = 45.0       # min seconds between two auto clips

    def update(self, data: dict) -> "SessionSettings":
        for k, v in (data or {}).items():
            if hasattr(self, k) and v is not None:
                cur = getattr(self, k)
                setattr(self, k, type(cur)(v) if not isinstance(cur, bool) else bool(v))
        if self.layout not in LAYOUTS:
            self.layout = "vertical-blur"
        return self

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "data")).resolve())
    ffmpeg: str = field(default_factory=lambda: _env("FFMPEG", "ffmpeg"))
    ffprobe: str = field(default_factory=lambda: _env("FFPROBE", "ffprobe"))
    segment_seconds: float = field(default_factory=lambda: _f("SEGMENT_SECONDS", 2.0))
    buffer_minutes: float = field(default_factory=lambda: _f("BUFFER_MINUTES", 10.0))
    stream_quality: str = field(default_factory=lambda: _env("QUALITY", "best"))
    encoder: str = field(default_factory=lambda: _env("ENCODER", "auto"))  # auto|libx264|h264_nvenc|h264_qsv|h264_amf
    threads: int = field(default_factory=lambda: int(_f("THREADS", 2)))
    low_priority: bool = field(default_factory=lambda: _b("LOW_PRIORITY", True))
    # YouTube sometimes answers "Sign in to confirm you're not a bot". Pass your own login:
    cookies_from_browser: str = field(default_factory=lambda: _env("COOKIES_FROM_BROWSER", ""))  # firefox|chrome|edge|brave
    cookies_file: str = field(default_factory=lambda: _env("COOKIES_FILE", ""))  # Netscape cookies.txt
    whisper_model: str =field(default_factory=lambda: _env("WHISPER_MODEL", "base"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))  # any OpenAI-compatible /v1
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    discord_webhook: str = field(default_factory=lambda: _env("DISCORD_WEBHOOK", ""))
    discord_auto: bool = field(default_factory=lambda: _b("DISCORD_AUTO", False))
    youtube_secrets: str = field(default_factory=lambda: _env("YOUTUBE_CLIENT_SECRETS", ""))
    title_template: str = field(default_factory=lambda: _env("TITLE_TEMPLATE", "{channel} {reason} 😱"))
    hashtags: str = field(default_factory=lambda: _env("HASHTAGS", "#shorts #gaming #clips"))
    defaults: SessionSettings = field(default_factory=lambda: SessionSettings(
        layout=_env("LAYOUT", "vertical-blur"),
        auto_clip=_b("AUTO_CLIP", True),
        threshold=_f("THRESHOLD", 70.0),
        pre=_f("PRE", 25.0),
        post=_f("POST", 8.0),
        chat=_b("CHAT", True),
        captions=_b("CAPTIONS", False),
        cooldown=_f("COOLDOWN", 45.0),
    ))

    @property
    def ytdlp_auth(self) -> list[str]:
        if self.cookies_file:
            return ["--cookies", self.cookies_file]
        if self.cookies_from_browser:
            return ["--cookies-from-browser", self.cookies_from_browser]
        return []

    @property
    def clips_dir(self) -> Path:
        return self.data_dir / "clips"

    @property
    def buffers_dir(self) -> Path:
        return self.data_dir / "buffers"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    def ensure_dirs(self) -> None:
        for d in (self.clips_dir, self.buffers_dir, self.downloads_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    _load_dotenv(Path.cwd() / ".env")
    cfg = Config()
    cfg.ensure_dirs()
    return cfg
