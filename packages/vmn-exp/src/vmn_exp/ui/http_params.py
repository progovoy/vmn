#!/usr/bin/env python3
"""Small request/response header helpers for vmn-exp ui routes."""
import mimetypes
from urllib.parse import quote

# One page of leaderboard rows or log entries, whatever a client asks for.
MAX_PAGE = 1000


def clamp_page(offset, limit, max_page=MAX_PAGE):
    """``(offset, limit)`` clamped to what one response may carry."""
    limit = None if limit is None else max(0, min(int(limit), max_page))
    return max(0, int(offset or 0)), limit


def key_list(keys):
    """``"a,b"`` -> ``["a", "b"]``; None (all metrics) when not given."""
    if keys is None:
        return None
    return [k for k in (part.strip() for part in keys.split(",")) if k]


def attachment(filename):
    """``Content-Disposition`` for any name: RFC 5987 ``filename*`` plus a
    quoted ASCII fallback that no quote or non-latin-1 char can break."""
    fallback = "".join(
        c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def media_type(filename):
    """The ``Content-Type`` a download of *filename* is served with."""
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"
