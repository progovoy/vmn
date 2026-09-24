#!/usr/bin/env python3
"""JSON responses that survive non-finite floats, rendered off the event loop.

Metrics are truthfully stored as NaN/inf when a run diverges, but strict JSON
has no token for them and Starlette refuses to emit one — so a single NaN
anywhere in a payload used to turn the whole leaderboard into a 500. Here they
go out as ``null``, which every client already treats as "no value".

Rendering uses ``orjson`` when it is installed (the ``ui`` extra pulls it in),
the stdlib otherwise. FastAPI encodes a handler's return value on the event
loop; heavy handlers return :func:`json_response` instead, which renders (and
gzips) inside the sync handler's worker thread and answers ``304`` to a
matching ``If-None-Match``.
"""
import datetime
import gzip
import hashlib
import json
import math

from fastapi.responses import JSONResponse, Response

try:
    import orjson
except ImportError:  # pragma: no cover - exercised by monkeypatching
    orjson = None

# Below this, compressing costs more than it saves (matches the middleware).
GZIP_MIN_BYTES = 1000
GZIP_LEVEL = 5


def _finite_or_none(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite_or_none(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_or_none(v) for v in value]
    return value


def _default(value):
    """What FastAPI's encoder would have made of a non-JSON value."""
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _stdlib_dumps(content):
    return json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        default=_default,
    ).encode("utf-8")


def _safe_stdlib(content):
    try:
        return _stdlib_dumps(content)  # fast path: nothing to scrub
    except ValueError:
        return _stdlib_dumps(_finite_or_none(content))


def render_json(content):
    """Compact UTF-8 JSON bytes; NaN/inf become ``null``."""
    if orjson is not None:
        try:
            # orjson already writes non-finite floats as null.
            return orjson.dumps(content, default=_default, option=orjson.OPT_NON_STR_KEYS)
        except TypeError:  # e.g. an int beyond 64 bits
            pass
    return _safe_stdlib(content)


class SafeJSONResponse(JSONResponse):
    def render(self, content):
        return render_json(content)


def _quoted(etag):
    return etag if etag.startswith(('"', 'W/"')) else f'"{etag}"'


def _opaque(tag):
    tag = tag.strip()
    return tag[2:] if tag.startswith("W/") else tag


def _matches(if_none_match, etag):
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    wanted = _opaque(etag)
    return any(_opaque(tag) == wanted for tag in if_none_match.split(","))


def _accepts_gzip(request):
    return request is not None and "gzip" in request.headers.get("accept-encoding", "")


def json_response(payload, etag=None, request=None, status_code=200):
    """A fully rendered JSON :class:`Response` with ``Cache-Control: no-cache``.

    *etag* (quoted if needed) is sent as ``ETag``; without one, a digest of the
    body is used when *request* is given. A request whose ``If-None-Match``
    matches gets an empty ``304``. The body is gzipped here, in the caller's
    thread, when the request accepts it, so the middleware passes it through.
    """
    body = render_json(payload)
    headers = {"Cache-Control": "no-cache"}
    if etag is None and request is not None:
        etag = hashlib.blake2b(body, digest_size=16).hexdigest()
    if etag is not None:
        headers["ETag"] = _quoted(etag)
        if request is not None and _matches(
            request.headers.get("if-none-match"), headers["ETag"]
        ):
            return Response(status_code=304, headers=headers)
    if _accepts_gzip(request) and len(body) >= GZIP_MIN_BYTES:
        body = gzip.compress(body, compresslevel=GZIP_LEVEL)
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"
    return Response(
        body, status_code=status_code, media_type="application/json", headers=headers
    )
