"""Validation of a report publish payload (docs/plans/13-reports-comments.md §8.1).

The client sends the data each panel already rendered; the server checks it
is a ``{panel-id: payload}`` object within the size caps, and that every run
it names (``{app, verstr}`` / ``{app, verstrs}`` objects) exists.
"""
import json
import re

from fastapi import HTTPException

MAX_PANEL_BYTES = 2 * 1024 * 1024
MAX_REVISION_BYTES = 50 * 1024 * 1024
_PANEL_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def validate_publish(storage, body):
    """``(rev, data)`` of a publish *body*, or an HTTPException."""
    rev, data = body.get("rev"), body.get("data")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        raise HTTPException(400, "rev must be a positive integer")
    if not isinstance(data, dict):
        raise HTTPException(400, "data must be an object of panel-id -> payload")
    _check_sizes(data)
    missing = sorted(f"{app}/{verstr}" for app, verstr in _run_refs(data)
                     if not storage.exists(app, verstr))
    if missing:
        raise HTTPException(400, f"Unknown runs: {', '.join(missing)}")
    return rev, data


def _check_sizes(data):
    total = 0
    for panel_id, payload in data.items():
        if not _PANEL_ID_RE.match(panel_id) or panel_id == "index":
            raise HTTPException(400, f"Invalid panel id {panel_id!r}")
        size = len(json.dumps(payload))
        if size > MAX_PANEL_BYTES:
            raise HTTPException(413, f"Panel {panel_id!r} data exceeds {MAX_PANEL_BYTES} bytes")
        total += size
    if total > MAX_REVISION_BYTES:
        raise HTTPException(413, f"Published data exceeds {MAX_REVISION_BYTES} bytes")


def _run_refs(node):
    """Every ``(app, verstr)`` named anywhere in *node*."""
    if isinstance(node, list):
        for item in node:
            yield from _run_refs(item)
    elif isinstance(node, dict):
        app = node.get("app")
        if isinstance(app, str):
            if isinstance(node.get("verstr"), str):
                yield app, node["verstr"]
            for verstr in node.get("verstrs") or ():
                if isinstance(verstr, str):
                    yield app, verstr
        for value in node.values():
            yield from _run_refs(value)
