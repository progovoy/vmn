#!/usr/bin/env python3
"""Small request/response header helpers for vmn ui routes."""
from urllib.parse import quote


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
