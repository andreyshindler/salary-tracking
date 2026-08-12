"""Serves the Mini App and receives what it submits.

Two routes matter. The page itself is static. The submission is a POST, because
the diary is launched from an *inline* ``web_app`` button and Telegram does not
deliver ``sendData`` from those — the page has to reach the bot itself.

That makes this endpoint the one place a request from outside Telegram could
reach the database, so it carries no session and trusts nothing: identity comes
from the signed launch parameters Telegram gave the page, checked against the
bot token by :mod:`salary_bot.core.webauth`.

It runs in the bot's own event loop rather than as a second process — one
container, one thing to supervise.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

from aiohttp import web

log = logging.getLogger(__name__)

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"

# (init_data, payload) -> (http status, message for the user)
Submit = Callable[[str, str], Awaitable[tuple[int, str]]]

# Bigger than any real submission — two short times and a date — so a runaway
# or hostile body is dropped before it is parsed.
MAX_BODY_BYTES = 8 * 1024


async def _index(_request: web.Request) -> web.Response:
    return web.FileResponse(
        WEBAPP_DIR / "index.html",
        headers={
            # The page is versioned with the deployment, and Telegram caches
            # aggressively; no-cache keeps an upgrade from showing a stale app.
            "Cache-Control": "no-cache",
            # It is framed by the Telegram client, so it must not be denied.
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


def _make_submit_handler(submit: Submit | None):
    async def handler(request: web.Request) -> web.Response:
        if submit is None:      # only in tests, and when serving the page alone
            return web.json_response({"message": "not accepting submissions"},
                                     status=503)

        if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
            return web.json_response({"message": "too large"}, status=413)

        try:
            body = json.loads(await request.content.read(MAX_BODY_BYTES + 1))
        except (ValueError, UnicodeDecodeError):
            return web.json_response({"message": "malformed request"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"message": "malformed request"}, status=400)

        init_data = body.get("initData")
        shift = body.get("shift")
        if not isinstance(init_data, str) or not isinstance(shift, str):
            return web.json_response({"message": "malformed request"}, status=400)

        status, message = await submit(init_data, shift)
        return web.json_response({"message": message}, status=status)

    return handler


def build_app(submit: Submit | None = None) -> web.Application:
    app = web.Application()
    handler = _make_submit_handler(submit)
    app.add_routes([
        # Registered before the catch-all, and under both spellings: hosting the
        # app at /salary means the proxy either strips the prefix or keeps it,
        # and the page cannot tell which it will be.
        web.post("/api/shift", handler),
        web.post("/{prefix:.*}/api/shift", handler),

        web.get("/healthz", _health),
        web.get("/", _index),
        # Catch-all, so a path-prefixed deployment works whichever way the
        # reverse proxy is configured. It is a single self-contained file with
        # no assets, so there is nothing else a GET could legitimately be
        # asking for.
        web.get("/{tail:.*}", _index),
    ])
    return app


async def start(host: str, port: int, submit: Submit | None = None) -> web.AppRunner:
    page = WEBAPP_DIR / "index.html"
    if not page.is_file():
        # Without this the failure surfaces as a bare 404 inside Telegram, with
        # nothing to say the packaging is at fault.
        raise RuntimeError(
            f"the Mini App page is missing at {page}. It is a data file rather "
            "than a module, so it only ships if package-data is declared."
        )

    runner = web.AppRunner(build_app(submit), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Mini App served on http://%s:%s", host, port)
    return runner
