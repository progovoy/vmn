"""Registry log: alias moves and version status changes.

Entries are written as JSON lines to a single ``registry.log.jsonl`` auxiliary
file inside the model header record directory.  The fold logic (from
``vmn_exp.registry.fold``) resolves aliases and statuses from the raw entries.
"""
from __future__ import annotations

import json
import os
import socket

from vmn_exp.registry.fold import fold_registry, next_ts
from vmn_exp.registry.names import valid_alias_name
from vmn_exp.registry.store import REGISTRY_APP

LOG_FILE = "registry.log.jsonl"


class AliasConflict(Exception):
    """Raised when a ``set_alias`` call's ``expect`` does not match reality."""


def actor_identity() -> dict:
    """A best-effort identity dict for the current writer."""
    writer = os.environ.get("VMN_WRITER_ID") or _hostname()
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    return {"writer": writer, "user": user}


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _read_log(storage, model_name: str) -> list[dict]:
    """Return all raw log entries for *model_name*."""
    raw = storage.load_file(REGISTRY_APP, model_name, LOG_FILE)
    if not raw:
        return []
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _append_entry(storage, model_name: str, entry: dict) -> None:
    """Append one JSON line to the model's log."""
    existing = storage.load_file(REGISTRY_APP, model_name, LOG_FILE) or b""
    if isinstance(existing, str):
        existing = existing.encode("utf-8")
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    storage.save_file(REGISTRY_APP, model_name, LOG_FILE, existing + line.encode())


def _last_ts(entries: list[dict]) -> str | None:
    """Return the latest timestamp seen in *entries*, or None."""
    ts_values = [e.get("ts") for e in entries if e.get("ts")]
    return max(ts_values) if ts_values else None


def _now_iso() -> str:
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")


def set_alias(
    storage,
    model_name: str,
    alias: str,
    version: int,
    expect: int | None = None,
) -> None:
    """Move *alias* to point to *version*.

    Raises :class:`AliasConflict` when *expect* is given and the alias
    currently points to a different version.
    """
    if not valid_alias_name(alias):
        raise ValueError(f"Invalid alias name {alias!r}")

    entries = _read_log(storage, model_name)
    if expect is not None:
        folded = fold_registry(entries)
        current = folded["aliases"].get(alias)
        if current != expect:
            raise AliasConflict(
                f"Alias {alias!r} points to {current!r}, not {expect!r}"
            )

    actor = actor_identity()
    ts = next_ts(_last_ts(entries), _now_iso())
    pos = len(entries)
    entry = {
        "type": "alias",
        "alias": alias,
        "version": version,
        "ts": ts,
        "writer": actor["writer"],
        "pos": pos,
        "actor": actor,
    }
    _append_entry(storage, model_name, entry)


def remove_alias(storage, model_name: str, alias: str) -> None:
    """Tombstone *alias* (set its version to None)."""
    if not valid_alias_name(alias):
        raise ValueError(f"Invalid alias name {alias!r}")
    entries = _read_log(storage, model_name)
    actor = actor_identity()
    ts = next_ts(_last_ts(entries), _now_iso())
    pos = len(entries)
    entry = {
        "type": "alias",
        "alias": alias,
        "version": None,
        "ts": ts,
        "writer": actor["writer"],
        "pos": pos,
        "actor": actor,
    }
    _append_entry(storage, model_name, entry)


def set_version_status(
    storage, model_name: str, version: int, status: str
) -> None:
    """Record a status change for *version*."""
    valid_statuses = {"active", "deprecated", "deleted"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status {status!r}; must be one of {valid_statuses}")
    entries = _read_log(storage, model_name)
    actor = actor_identity()
    ts = next_ts(_last_ts(entries), _now_iso())
    pos = len(entries)
    entry = {
        "type": "status",
        "version": version,
        "status": status,
        "ts": ts,
        "writer": actor["writer"],
        "pos": pos,
        "actor": actor,
    }
    _append_entry(storage, model_name, entry)
