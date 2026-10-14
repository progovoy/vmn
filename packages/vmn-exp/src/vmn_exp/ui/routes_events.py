#!/usr/bin/env python3
"""``GET .../apps/{app}/events?scope=<verstr>|top``: the app's changes as
Server-Sent Events (plan 23 S5, :mod:`vmn_exp.ui.live_events`).

Only a background refresher keeps a snapshot fresh without a request
paying for it, so without one (an embedded ``create_app``) the route is a
404 ``no_live_events`` and the client keeps polling. Past
``MAX_STREAMS`` open streams it is a 503 (the client polls too)."""
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER

from vmn_exp.ui import live_events

NO_LIVE_EVENTS = "no_live_events"
TOO_MANY_STREAMS = "too_many_streams"


class EventStreamResponse(StreamingResponse):
    """A text/event-stream giving its stream slot back however it ends
    (finished, the client gone, the server stopping)."""

    def __init__(self, content, release):
        super().__init__(content, media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx: pass each event on at once
        })
        self._release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()


def register(app, prefix, reader_for, background, segment):
    """Add the route; *reader_for(ws_name, app_tag)* → a blocking callable
    answering the app's current snapshot (raising 4xx for a bad workspace
    or app); *background*: whether a background refresher serves them."""
    slots = live_events.StreamSlots(live_events.MAX_STREAMS)
    app.state.event_slots = slots

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/events",
             dependencies=[require(VIEWER)])
    async def app_events(ws_name: str, app_tag: str, scope: str = None):
        if not background:
            return JSONResponse({"detail": "Live events need the background refresher",
                                 "reason": NO_LIVE_EVENTS}, status_code=404)
        if scope is not None:
            segment(scope, "scope")
        read = await run_in_threadpool(reader_for, ws_name, app_tag)
        if not slots.acquire():
            return JSONResponse({"detail": "Too many live streams", "reason": TOO_MANY_STREAMS},
                                status_code=503, headers={"Retry-After": "30"})
        stream = live_events.event_stream(lambda: run_in_threadpool(read), scope)
        return EventStreamResponse(stream, slots.release)
