"""Registry log writes: actor identity, alias moves, version status changes.

Each write appends one entry to the model record's per-writer JSONL log (the
same segments mechanism used by the experiment log) and flushes to the remote
immediately, so a second host that calls read_entries after a write sees it.

fold_registry (vmn_exp.registry.fold) is chunking-invariant, so concurrent
writers on the same model never corrupt state.
"""
from __future__ import annotations

import os
import subprocess

from vmn_exp.core.writer import flush_log, get_writer_id
from vmn_exp.core.record_format import stamped
from vmn_exp.registry.fold import fold_registry, fold_uses, now_iso as _reg_ts, next_ts
from vmn_exp.registry.names import HEADER_RECORD, USES_RECORD
from vmn_exp.registry.store import registry_storage


# ---------------------------------------------------------------------------
# Actor identity
# ---------------------------------------------------------------------------

def actor_identity() -> dict:
    """Return a plain dict identifying the writer.

    Fields:
      writer         — experiment-log writer id (VMN_WRITER_ID / HOSTNAME)
      git_user_email — git config user.email, best-effort (empty on failure)
      os_user        — $USER / $LOGNAME / os.getlogin(), best-effort
    """
    return {
        "writer": get_writer_id(),
        "git_user_email": _git_user_email(),
        "os_user": _os_user(),
    }


def _git_user_email() -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _os_user() -> str:
    for key in ("USER", "LOGNAME", "USERNAME"):
        val = os.environ.get(key)
        if val:
            return val
    try:
        return os.getlogin()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Reading entries
# ---------------------------------------------------------------------------

def read_entries(storage, model: str, record: str = HEADER_RECORD) -> list:
    """Return all log entries of *model*'s *record* (its audit log by
    default, ``uses`` for its usage log), merged across all writers."""
    return registry_storage(storage).load_merged_log(model, record)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _max_ts(entries: list) -> str | None:
    """Greatest 'ts' value across all entries, or None when there are none."""
    return max(
        (e["ts"] for e in entries if isinstance(e.get("ts"), str)), default=None
    )


def _writer_pos(entries: list, writer_id: str) -> int:
    """Number of entries already written by *writer_id* — used as the next pos."""
    return sum(1 for e in entries if e.get("writer") == writer_id)


def _build_entry(
    entries: list,
    entry_type: str,
    actor: dict | None,
    **fields,
) -> dict:
    writer_id = get_writer_id()
    pos = _writer_pos(entries, writer_id)
    ts = next_ts(_max_ts(entries), _reg_ts())
    return {
        "type": entry_type,
        "ts": ts,
        "writer": writer_id,
        "pos": pos,
        "actor": actor if actor is not None else actor_identity(),
        **fields,
    }


def _append_entry(storage, model: str, entry: dict, record: str = HEADER_RECORD) -> None:
    """Append *entry* to *model*'s *record* log and flush to remote so readers see it."""
    reg = registry_storage(storage)
    reg.append_log_entry(model, record, entry["writer"], entry)
    flush_log(reg, model, record)


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------

def set_alias(
    storage,
    model: str,
    alias: str,
    version,
    *,
    expect=None,
    actor: dict | None = None,
) -> None:
    """Point *alias* at *version* in *model*'s registry log.

    *version* is an int (point) or None (tombstone / removal).
    *expect* is the version the caller believes the alias currently holds, or
    the string ``"none"`` if it expects the alias to be absent.  A mismatch
    raises ``ValueError`` before any write.
    """
    entries = read_entries(storage, model)
    if expect is not None:
        _check_expect(alias, expect, fold_registry(entries))
    entry = _build_entry(entries, "alias", actor, alias=alias, version=version)
    _append_entry(storage, model, entry)


def remove_alias(
    storage,
    model: str,
    alias: str,
    *,
    expect=None,
    actor: dict | None = None,
) -> None:
    """Tombstone *alias* in *model*'s registry log (version → None)."""
    set_alias(storage, model, alias, None, expect=expect, actor=actor)


def set_version_status(
    storage,
    model: str,
    version: int,
    status: str,
    *,
    actor: dict | None = None,
) -> None:
    """Record a status change for *version* of *model*.

    *status* is one of ``"active"``, ``"deprecated"``, ``"deleted"``.
    Deleting a version that an alias still points to raises ``ValueError``;
    remove the alias first.
    """
    entries = read_entries(storage, model)
    if status == "deleted":
        fold = fold_registry(entries)
        pointing = [a for a, v in fold["aliases"].items() if v == version]
        if pointing:
            raise ValueError(
                f"Cannot delete version {version} of model {model!r}: "
                f"aliases {pointing!r} still point to it — remove them first."
            )
    entry = _build_entry(entries, "status", actor, version=version, status=status)
    _append_entry(storage, model, entry)


def record_use(
    storage,
    model: str,
    version: int,
    app: str,
    verstr: str,
    *,
    actor: dict | None = None,
) -> None:
    """Record that run *verstr* of *app* used *version* of *model*.

    Appends to the model's ``uses`` record, never to the model's own
    log, so the model's audit and the registry's run-models cache stay put.
    A run already recorded for *version* writes nothing.
    """
    entries = read_entries(storage, model, USES_RECORD)
    if not entries:  # a log needs its record: create it on the first use
        header = {"model": model, "type": "uses_header", "timestamp": _reg_ts()}
        registry_storage(storage).create_exclusive(model, USES_RECORD, stamped(header), {})
    run = {"app": app, "verstr": verstr}
    if any(e.get("type") == "use" and e.get("version") == version and e.get("run") == run
           for e in entries):
        return
    entry = _build_entry(entries, "use", actor, version=version, run=run)
    _append_entry(storage, model, entry, USES_RECORD)


def read_uses(storage, model: str) -> dict:
    """``{version: [{app, verstr, ts}]}`` of the runs recorded using *model*."""
    return fold_uses(read_entries(storage, model, USES_RECORD))


# ---------------------------------------------------------------------------
# expect check (extracted for clarity)
# ---------------------------------------------------------------------------

def _check_expect(alias: str, expect, fold: dict) -> None:
    current = fold["aliases"].get(alias)
    if expect == "none" and current is not None:
        raise ValueError(
            f"Expected alias {alias!r} to be absent, "
            f"but it currently points to version {current}."
        )
    if expect != "none" and current != expect:
        raise ValueError(
            f"Expected alias {alias!r} to point to version {expect!r}, "
            f"but it is {current!r}."
        )
