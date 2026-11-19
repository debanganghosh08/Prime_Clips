"""FastAPI server: REST + Server-Sent Events + the dashboard. See docs/API.md."""
from __future__ import annotations

import asyncio
import json
import queue
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .config import Config
from .core import App

WEB = Path(__file__).parent / "web"


def create_app(cfg: Config) -> FastAPI:
    core = App(cfg)

    @asynccontextmanager
    async def lifespan(_):
        yield
        core.shutdown()

    api = FastAPI(title="Prime Clips", docs_url="/api/docs", lifespan=lifespan)
    api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    api.state.core = core

    def session(sid: str):
        s = core.sessions.get(sid)
        if not s:
            raise HTTPException(404, "no such session")
        return s

    def clip(cid: str):
        c = core.library.get(cid)
        if not c:
            raise HTTPException(404, "no such clip")
        return c

    @api.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB / "index.html")

    @api.get("/api/status")
    def status():
        return core.status()

    @api.post("/api/live/start")
    def live_start(body: dict = Body(...)):
        url = (body or {}).pop("url", "").strip()
        if not url:
            raise HTTPException(400, "url is required")
        return core.start_live(url, body).to_api()

    @api.get("/api/live/{sid}")
    def live_get(sid: str):
        return session(sid).to_api(full=True)

    @api.post("/api/live/{sid}/stop")
    def live_stop(sid: str):
        s = session(sid)
        s.stop()
        return s.to_api()

    @api.post("/api/live/{sid}/clip")
    def live_clip(sid: str, body: dict = Body(default={})):
        try:
            return core.manual_clip(session(sid), float(body.get("seconds", 30)), body.get("layout")).to_api(cfg)
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @api.post("/api/clip")
    def clip_latest(body: dict = Body(default={})):
        s = core.latest_session()
        if not s:
            raise HTTPException(409, "no live session running")
        return live_clip(s.id, body)

    @api.post("/api/vod")
    def vod(body: dict = Body(...)):
        url = (body.get("url") or "").strip()
        if not url:
            raise HTTPException(400, "url is required")
        return core.start_vod(url, top_n=int(body.get("top_n", 5)), layout=body.get("layout"),
                              captions_on=bool(body.get("captions", False)),
                              min_len=float(body.get("min_len", 20)), max_len=float(body.get("max_len", 45)),
                              ai_pick=bool(body.get("ai", False)))

    @api.get("/api/clips")
    def clips():
        return [c.to_api(cfg) for c in core.library.all()]

    @api.get("/api/clips/{cid}")
    def clip_get(cid: str):
        return clip(cid).to_api(cfg)

    @api.get("/api/clips/{cid}/file/{kind}")
    def clip_file(cid: str, kind: str):
        if kind not in ("raw", "vertical", "thumb"):
            raise HTTPException(404)
        c = clip(cid)
        p = c.path(cfg, kind)
        if not p.exists():
            raise HTTPException(404, "file not ready")
        name = f"{c.channel}_{c.id}_{kind}{p.suffix}"
        return FileResponse(p, filename=name if kind != "thumb" else None)

    @api.delete("/api/clips/{cid}")
    def clip_delete(cid: str):
        clip(cid)
        core.library.delete(cid)
        return {"ok": True}

    @api.post("/api/clips/{cid}/publish")
    def clip_publish(cid: str, body: dict = Body(...)):
        c = clip(cid)
        if c.status != "ready":
            raise HTTPException(409, "clip is not ready yet")
        try:
            return core.publish(c, body.get("target", "")).to_api(cfg)
        except Exception as e:
            raise HTTPException(400, str(e))

    @api.get("/api/events")
    async def events():
        q = core.bus.subscribe()

        async def gen():
            try:
                yield "retry: 2000\n\n"
                idle = 0
                while True:
                    try:
                        msg = q.get_nowait()
                        idle = 0
                        yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        await asyncio.sleep(0.2)
                        idle += 1
                        if idle >= 75:  # keep-alive every ~15 s
                            idle = 0
                            yield ": ping\n\n"
            finally:
                core.bus.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return api
