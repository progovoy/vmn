"""A slow per-run read whose client has gone is skipped: an abandoned
request (a hover prefetch, a page left before it answered) never spends a
slow-read thread on S3 reads nobody waits for."""
import asyncio
import inspect

import pytest

pytest.importorskip("fastapi")
from fastapi import Request

from vmn_exp.ui.slow_reads import slow_read


class _Request:
    def __init__(self, gone):
        self.gone = gone

    async def is_disconnected(self):
        return self.gone


def _route(calls):
    def route(verstr: str):
        calls.append(verstr)
        return {"verstr": verstr}
    return route


def _call(wrapped, gone, **kwargs):
    hidden = next(n for n, p in inspect.signature(wrapped).parameters.items()
                  if p.annotation is Request)
    return asyncio.run(wrapped(**kwargs, **{hidden: _Request(gone)}))


def test_a_read_whose_client_left_is_skipped():
    calls = []
    response = _call(slow_read(_route(calls)), gone=True, verstr="v")
    assert calls == []
    assert response.status_code == 499


def test_a_read_whose_client_waits_runs():
    calls = []
    assert _call(slow_read(_route(calls)), gone=False, verstr="v") == {"verstr": "v"}
    assert calls == ["v"]


def test_a_route_taking_the_request_gets_it():
    seen = []

    def route(verstr: str, request: Request):
        seen.append(request)
        return verstr

    wrapped = slow_read(route)
    params = inspect.signature(wrapped).parameters
    assert [n for n, p in params.items() if p.annotation is Request] == ["request"]
    req = _Request(False)
    assert asyncio.run(wrapped(verstr="v", request=req)) == "v"
    assert seen == [req]
