"""Get the clip out there FIRST.

* Discord webhook: instant ping (with the file attached if < 24 MB) to your clipping
  team / phone, so you can post from anywhere. Pure stdlib.
* YouTube Shorts upload (experimental): pip install google-api-python-client google-auth-oauthlib
  and point PRIMECLIPS_YOUTUBE_CLIENT_SECRETS at your OAuth client_secrets.json.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
import urllib.request
from pathlib import Path

from .config import Config

log = logging.getLogger("primeclips.publish")


def discord(cfg: Config, text: str, file: Path | None = None) -> None:
    if not cfg.discord_webhook:
        raise RuntimeError("set PRIMECLIPS_DISCORD_WEBHOOK first")
    boundary = uuid.uuid4().hex
    parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
              f"Content-Type: application/json\r\n\r\n{json.dumps({'content': text[:1900]})}\r\n").encode()]
    if file and file.exists() and file.stat().st_size < 24 * 1024 * 1024:
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; '
                      f'filename="{file.name}"\r\nContent-Type: video/mp4\r\n\r\n').encode()
                     + file.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(cfg.discord_webhook, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "User-Agent": "PrimeClips (https://github.com/debanganghosh08/Prime_Clips)"})
    urllib.request.urlopen(req, timeout=120).read()


def youtube(cfg: Config, file: Path, title: str, description: str = "") -> str:
    """Upload as a Short. Returns the video URL. First run opens a browser for OAuth."""
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaFileUpload  # type: ignore
    except ImportError as e:
        raise RuntimeError("pip install google-api-python-client google-auth-oauthlib") from e
    if not cfg.youtube_secrets or not Path(cfg.youtube_secrets).exists():
        raise RuntimeError("set PRIMECLIPS_YOUTUBE_CLIENT_SECRETS to your OAuth client_secrets.json")
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    token = cfg.data_dir / "youtube_token.json"
    creds = Credentials.from_authorized_user_file(str(token), scopes) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(cfg.youtube_secrets, scopes).run_local_server(port=0)
        token.write_text(creds.to_json(), encoding="utf-8")
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {"snippet": {"title": (title[:90] + " #Shorts")[:100], "description": description,
                        "categoryId": "20"},  # 20 = Gaming
            "status": {"privacyStatus": os.environ.get("PRIMECLIPS_YOUTUBE_PRIVACY", "public"),
                       "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(file), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"https://youtube.com/shorts/{resp['id']}"
