#!/usr/bin/env python3
"""Input / dataset provenance entries for an experiment log.

An ``input`` log entry records a dataset, model checkpoint, or any other
artifact a run consumed.  Multiple writers can record inputs concurrently;
:func:`fold_inputs` (and the main fold in :mod:`experiment_fold`) apply the
same latest-(ts, writer, pos)-wins rule that tags use, so the merged view is
always deterministic.

Pure: no I/O, no storage, no clock.
"""
import os
import re

_VALID_FIELDS = frozenset({"type", "uri", "name", "digest", "kind", "ts"})
_VALID_SUBFIELDS = frozenset({"uri", "digest", "kind"})


def default_input_name(uri):
    """Basename of *uri* without its extension, sanitized to a safe identifier.

    Trailing slashes are stripped first so ``s3://bucket/dir/`` yields ``dir``.
    Characters that are not alphanumeric, ``-``, or ``_`` are replaced with
    ``_``; leading/trailing underscores are stripped.
    """
    path = uri.rstrip("/")
    basename = os.path.basename(path) or path
    root, _ = os.path.splitext(basename)
    sanitized = re.sub(r"[^A-Za-z0-9_\-]", "_", root)
    return sanitized.strip("_") or "input"


def create_input_entry(uri, name=None, digest=None, kind=None, ts=None):
    """A log entry recording that a run consumed the artifact at *uri*.

    ``{"type": "input", "uri", "name", "digest", "kind", "ts"}``

    *name* defaults to :func:`default_input_name(uri) <default_input_name>`.
    *digest* and *kind* are optional provenance hints (e.g. ``"sha256:…"``
    and ``"dataset"``).  *ts* is an ISO-8601 timestamp; the fold uses it as
    the primary ordering key.
    """
    return {
        "type": "input",
        "uri": uri,
        "name": name if name is not None else default_input_name(uri),
        "digest": digest,
        "kind": kind,
        "ts": ts,
    }


def valid_input_entry(e):
    """True when *e* is a well-formed input log entry (no extra fields)."""
    if not isinstance(e, dict):
        return False
    if e.get("type") != "input":
        return False
    if not e.get("uri"):
        return False
    extra = set(e.keys()) - _VALID_FIELDS
    if extra:
        return False
    return True


def fold_inputs(entries):
    """``{name: {uri, digest, kind}}`` folded from *entries* with latest-ts-wins.

    Only ``type == "input"`` entries are processed; all others are ignored.
    When two entries share a name and timestamp the one that appears later in
    *entries* wins (list-position tiebreak, matching :func:`fold_log`).
    """
    current = {}  # name → (value_dict, sort_key)
    for pos, entry in enumerate(entries):
        if not isinstance(entry, dict) or entry.get("type") != "input":
            continue
        name = entry.get("name")
        if not name:
            continue
        ts = entry.get("ts") or entry.get("timestamp") or ""
        key = (ts if isinstance(ts, str) else "", pos)
        existing = current.get(name)
        if existing is None or key >= existing[1]:
            value = {f: entry.get(f) for f in _VALID_SUBFIELDS}
            current[name] = (value, key)
    return {name: v for name, (v, _) in current.items()}
