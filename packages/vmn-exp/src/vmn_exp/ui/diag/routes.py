#!/usr/bin/env python3
"""``GET {prefix}/diag``: the dump as JSON, admin-only.

The route is async and builds the dump on the event loop, and its auth runs
on a thread of its own (:func:`authenticate`), so it answers while every
pool thread is busy — exactly when it is needed.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.ui.auth.authz import require_on_loop
from vmn_exp.ui.auth.principal import ADMIN
from vmn_exp.ui.diag.pools import capture_limiters
from vmn_exp.ui.diag.registry import build_dump
from vmn_exp.ui.responses import SafeJSONResponse

DIAG_PATH = "/diag"

# Off anyio's pools: authenticating a dump request never queues behind them.
_AUTH_THREADS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vmn-ui-diag-auth")


def is_diag_request(prefix, path):
    return path == prefix + DIAG_PATH


async def authenticate(chain, request):
    """``chain.authenticate(request)`` on the dump's own threads."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_AUTH_THREADS, chain.authenticate, request)


def register(app, prefix):
    app.router.on_startup.append(capture_limiters)

    @app.get(prefix + DIAG_PATH, dependencies=[require_on_loop(ADMIN)])
    async def diag_dump():
        capture_limiters()  # this loop's, whatever loop started up
        return SafeJSONResponse(build_dump())
