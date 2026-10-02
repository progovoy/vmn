"""Registry log fold: deterministic last-writer-wins alias and status resolution.

A registry log is an append-only sequence of dicts written by one or more
concurrent writers.  Entries may arrive chunked in any order.  The fold
resolves each alias and version status to the value carried by the entry with
the greatest ``(ts, writer, pos)`` key — the same tie-breaking used by the
experiment index (see ``version_stamp.core.experiment_fold._keep_latest``).

Storing ``(value, ts, writer, pos)`` as a flat 4-tuple means the comparison is
``key >= current[1:]``, avoiding a nested value/key pair per field.

Entry shapes
------------
Alias move / tombstone::

    {"type": "alias", "alias": <str>, "version": <int or None>,
     "ts": <iso>, "writer": <str>, "pos": <int>, "actor": {...}}

Version status change::

    {"type": "status", "version": <int>, "status": "active"|"deprecated"|"deleted",
     "ts": <iso>, "writer": <str>, "pos": <int>, "actor": {...}}

Version use (in the model scope's ``uses`` record, see ``fold_uses``)::

    {"type": "use", "version": <int>, "run": {"app", "verstr"},
     "ts": <iso>, "writer": <str>, "pos": <int>, "actor": {...}}

Pure: no storage, no clock.
"""
from __future__ import annotations

import datetime as _dt
from datetime import datetime, timedelta
from typing import Any


_ONE_MICROSECOND = timedelta(microseconds=1)


def _sort_key(entry: dict) -> tuple:
    """``(ts, writer, pos)`` comparison key for a registry entry."""
    ts = entry.get("ts", "")
    writer = entry.get("writer", "")
    pos = entry.get("pos", 0)
    return (
        ts if isinstance(ts, str) else "",
        writer if isinstance(writer, str) else "",
        pos if isinstance(pos, int) else 0,
    )


def _keep_latest(bucket: dict, field: Any, value: Any, key: tuple) -> None:
    """Update *bucket[field]* when *key* beats the stored key.

    Stores ``(value, *key)`` as a flat tuple so comparison is
    ``key >= current[1:]`` — one allocation, no nesting.
    """
    current = bucket.get(field)
    if current is None or key >= current[1:]:
        bucket[field] = (value,) + key


def fold_registry(entries: list) -> dict:
    """Fold *entries* into a registry snapshot.

    Returns a plain dict::

        {
            "aliases": {alias: version},   # tombstoned (None) aliases omitted
            "status":  {version: status},
            "audit":   [entries ordered ascending by (ts, writer, pos)],
        }

    The result is chunking-invariant: ``fold_registry(a + b)`` equals
    ``fold_registry(b + a)`` and ``fold_registry(shuffled(a + b))``.
    """
    _aliases: dict = {}
    _status: dict = {}

    # Compute sort keys once; reuse them for both the fold loop and the audit sort.
    dict_entries = [(e, _sort_key(e)) for e in entries if isinstance(e, dict)]

    for entry, key in dict_entries:
        etype = entry.get("type")
        if etype == "alias":
            alias = entry.get("alias")
            if alias is not None:
                _keep_latest(_aliases, alias, entry.get("version"), key)
        elif etype == "status":
            version = entry.get("version")
            status = entry.get("status")
            if version is not None and status is not None:
                _keep_latest(_status, version, status, key)

    aliases = {
        alias: stored[0]
        for alias, stored in _aliases.items()
        if stored[0] is not None
    }
    status = {version: stored[0] for version, stored in _status.items()}
    audit = [e for e, _ in sorted(dict_entries, key=lambda x: x[1])]
    return {"aliases": aliases, "status": status, "audit": audit}


def fold_uses(entries: list) -> dict:
    """``{version: [{app, verstr, ts}]}`` of the runs that used each version.

    One row per ``(version, run)``, from its earliest ``use`` entry (by
    ``(ts, writer, pos)``); rows ordered by that key. Chunking-invariant.
    """
    earliest: dict = {}
    for entry in entries:
        use = _use_of(entry)
        if use is None:
            continue
        key = _sort_key(entry)
        if use not in earliest or key < earliest[use]:
            earliest[use] = key
    uses: dict = {}
    for (n, app, verstr), key in sorted(earliest.items(), key=lambda kv: (kv[1], kv[0])):
        uses.setdefault(n, []).append({"app": app, "verstr": verstr, "ts": key[0]})
    return uses


def _use_of(entry) -> tuple | None:
    """``(version, app, verstr)`` of a well-formed ``use`` entry, else None."""
    if not isinstance(entry, dict) or entry.get("type") != "use":
        return None
    run, n = entry.get("run"), entry.get("version")
    if not isinstance(n, int) or not isinstance(run, dict):
        return None
    app, verstr = run.get("app"), run.get("verstr")
    if not (isinstance(app, str) and app and isinstance(verstr, str) and verstr):
        return None
    return n, app, verstr


def _parse_ts(ts: str) -> datetime | None:
    """Parse an ISO timestamp string to a :class:`datetime`."""
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def now_iso() -> str:
    """Return UTC now as ``%Y-%m-%dT%H:%M:%S.%f`` — always parseable by ``_parse_ts``."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def next_ts(prev_ts: str | None, now: str) -> str:
    """Return the timestamp a writer should use for its next entry.

    Guarantees the result is strictly greater than *prev_ts*, so the new entry
    beats every entry the writer has already read in the ``(ts, writer, pos)``
    order — even when the local clock is behind other writers.

    Algorithm: ``max(now, prev_ts + 1µs)``.

    Both *prev_ts* and *now* are ISO strings (``%Y-%m-%dT%H:%M:%S.%f``).
    *prev_ts* may be ``None`` for a writer that has seen no prior entries, in
    which case *now* is returned unchanged.
    """
    if prev_ts is None:
        return now
    prev_dt = _parse_ts(prev_ts)
    if prev_dt is None:
        return now
    now_dt = _parse_ts(now)
    if now_dt is None:
        return now
    candidate = prev_dt + _ONE_MICROSECOND
    result = max(candidate, now_dt)
    return result.strftime("%Y-%m-%dT%H:%M:%S.%f")
