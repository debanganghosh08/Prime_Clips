"""Live chat readers. Chat is the best hype signal there is: when something insane
happens, chat explodes with KEKW / OMEGALUL / "CLIP IT" a few seconds later.

* Twitch: anonymous IRC (no account, no API key, pure stdlib).
* YouTube: via the optional `chat-downloader` package.
* Kick: not yet (their chat sits behind Cloudflare). Detection falls back to audio.
"""
from __future__ import annotations

import logging
import random
import socket
import threading
from typing import Callable

log = logging.getLogger("primeclips.chat")

OnMessage = Callable[[str, str], None]  # (user, text)


class _Reader(threading.Thread):
    def __init__(self, on_message: OnMessage):
        super().__init__(daemon=True)
        self.on_message = on_message
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()


class TwitchChat(_Reader):
    HOST, PORT = "irc.chat.twitch.tv", 6667

    def __init__(self, channel: str, on_message: OnMessage):
        super().__init__(on_message)
        self.channel = channel.lower().lstrip("#")

    def run(self) -> None:
        backoff = 2
        while not self._halt.is_set():
            try:
                with socket.create_connection((self.HOST, self.PORT), timeout=10) as s:
                    s.settimeout(1.0)
                    nick = f"justinfan{random.randint(10000, 99999)}"
                    s.sendall(f"NICK {nick}\r\nJOIN #{self.channel}\r\n".encode())
                    log.info("twitch chat connected: #%s", self.channel)
                    backoff = 2
                    buf = b""
                    while not self._halt.is_set():
                        try:
                            data = s.recv(4096)
                        except socket.timeout:
                            continue
                        if not data:
                            break
                        buf += data
                        *lines, buf = buf.split(b"\r\n")
                        for raw in lines:
                            line = raw.decode(errors="replace")
                            if line.startswith("PING"):
                                s.sendall(b"PONG :tmi.twitch.tv\r\n")
                            elif " PRIVMSG " in line and line.startswith(":"):
                                user = line[1:line.find("!")]
                                text = line.split(" :", 1)[1] if " :" in line else ""
                                self.on_message(user, text)
            except Exception as e:  # network hiccup: reconnect with backoff
                if self._halt.is_set():
                    break
                log.warning("twitch chat dropped (%s), retrying in %ss", e, backoff)
                self._halt.wait(backoff)
                backoff = min(backoff * 2, 60)


class YouTubeChat(_Reader):
    def __init__(self, url: str, on_message: OnMessage):
        super().__init__(on_message)
        self.url = url

    def run(self) -> None:
        try:
            from chat_downloader import ChatDownloader  # type: ignore
        except ImportError:
            log.warning("YouTube chat needs `pip install chat-downloader`; using audio only")
            return
        while not self._halt.is_set():
            try:
                for msg in ChatDownloader().get_chat(self.url, message_groups=["messages"]):
                    if self._halt.is_set():
                        return
                    author = (msg.get("author") or {}).get("name", "?")
                    self.on_message(author, msg.get("message") or "")
            except Exception as e:
                log.warning("youtube chat error: %s", e)
                self._halt.wait(10)


def start_chat(platform: str, channel: str, url: str, on_message: OnMessage) -> _Reader | None:
    reader: _Reader | None = None
    if platform == "twitch":
        reader = TwitchChat(channel, on_message)
    elif platform == "youtube":
        reader = YouTubeChat(url, on_message)
    else:
        log.info("no chat reader for %s; hype detection uses audio only", platform)
    if reader:
        reader.start()
    return reader
