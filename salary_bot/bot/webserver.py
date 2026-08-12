"""Serves the Mini App's single HTML file.

Deliberately static-only: the app returns its result through Telegram's
``sendData``, not through an API call here, so this server never receives user
data and needs no authentication. Telegram delivers the payload to the bot as a
``web_app_data`` message on the same authenticated connection everything else
uses.

It runs in the bot's own event loop rather than as a second process — one
container, one thing to supervise.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

log = logging.getLogger(__name__)

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"


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


def build_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get("/healthz", _health),
        web.get("/", _index),
        # Catch-all, so a path-prefixed deployment works whichever way the
        # reverse proxy is configured. Hosting the app at /salary either
        # forwards "/" (prefix stripped) or "/salary/" (preserved), and there
        # is no way to tell from here — serving the page for any path makes
        # both correct. It is a single self-contained file with no assets, so
        # there is nothing else a request could legitimately be asking for.
        web.get("/{tail:.*}", _index),
    ])
    return app


async def start(host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Mini App served on http://%s:%s", host, port)
    return runner
