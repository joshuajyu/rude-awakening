"""HTTP endpoints Rootly (and you) call."""

import hmac
import json
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .alarm import AlarmController, Ringer
from .config import Settings
from .media import make_media_server

log = logging.getLogger(__name__)


def summarize(body: bytes) -> str:
    """A short, format-agnostic description of a webhook body for the log."""
    if not body:
        return "empty body"
    try:
        data = json.loads(body)
    except ValueError:
        return f"non-JSON body ({len(body)} bytes)"
    if not isinstance(data, dict):
        return f"JSON {type(data).__name__}"
    summary = "keys=[" + ", ".join(list(data)[:8]) + "]"
    title = _find_title(data)
    if title:
        summary += f" title={title[:100]!r}"
    return summary


def _find_title(data: dict, depth: int = 0) -> str | None:
    for key in ("title", "summary", "name", "description"):
        if isinstance(data.get(key), str) and data[key]:
            return data[key]
    if depth < 2:
        for value in data.values():
            if isinstance(value, dict) and (title := _find_title(value, depth + 1)):
                return title
    return None


def create_app(settings: Settings, ringer=None, serve_media: bool = True) -> FastAPI:
    ringer = ringer or Ringer(settings)
    alarm = AlarmController(ringer.ring)

    @asynccontextmanager
    async def lifespan(app):
        server = None
        if serve_media:
            server = make_media_server(settings.media_host, settings.media_port,
                                       settings.alarm_file, settings.media_type)
            threading.Thread(target=server.serve_forever, name="media", daemon=True).start()
            log.info("Serving alarm sound at %s", settings.media_url)
        yield
        await run_in_threadpool(alarm.stop)
        if server:
            server.shutdown()

    # No interactive docs: this is reachable from the internet.
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    expected = settings.webhook_token.encode()

    def require_token(x_webhook_token: str | None = Header(default=None)):
        if x_webhook_token is None or not hmac.compare_digest(x_webhook_token.encode(), expected):
            raise HTTPException(status_code=401, detail="invalid token")

    @app.post("/page", dependencies=[Depends(require_token)], status_code=202)
    async def page(request: Request):
        log.info("Page received: %s", summarize(await request.body()))
        started = await run_in_threadpool(alarm.start, "page", settings.alarm_volume, settings.alarm_timeout)
        if not started:
            log.info("Alarm already ringing; ignoring duplicate page")
            return {"status": "already_ringing"}
        return {"status": "ringing"}

    @app.post("/stop", dependencies=[Depends(require_token)])
    async def stop():
        stopped = await run_in_threadpool(alarm.stop)
        log.info("Stop requested (%s)", "stopped" if stopped else "nothing ringing")
        return {"status": "stopped" if stopped else "idle"}

    @app.post("/test", dependencies=[Depends(require_token)], status_code=202)
    async def test(request: Request):
        log.info("Test received: %s", summarize(await request.body()))
        started = await run_in_threadpool(alarm.start, "test", settings.test_volume, settings.test_duration)
        return {"status": "testing" if started else "already_ringing"}

    @app.get("/health")
    async def health(nest: bool = False):
        result = {"status": "ok", "alarm_active": alarm.active}
        if nest:
            result["nest_reachable"] = await run_in_threadpool(ringer.check)
        return result

    return app
