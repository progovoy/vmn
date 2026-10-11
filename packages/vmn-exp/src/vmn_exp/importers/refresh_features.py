"""``import-mlflow --refresh-features``: bring an already-imported run up to
date with its MLflow tags (plan 18 §3.6) without rewriting the record.

A record without a ``features`` entry at the current version — or whose
features lack the changes a ``--repo`` checkout now has — gets one built from
the tags, its branch inside (the metadata is left as it is). A record without a
note gets the MLflow note. The entry is appended under this host's writer and
flushed right away, a one-shot append like ``tag``: the import writer's log is
never touched, and no lock is taken.
"""
from __future__ import annotations

from typing import Any

from version_stamp.api import now_iso
from vmn_exp.core.writer import append_to_log, flush_log
from vmn_exp.importers.mlflow_features import NOTE, features_entry, needs_features, tag


def refresh_record(
    storage,
    app_name: str,
    verstr: str,
    run: dict[str, Any],
    metadata: dict[str, Any],
    logs: dict[str, list[dict[str, Any]]] | None,
    commit: dict[str, Any] | None = None,
) -> bool:
    """Refresh *verstr*, imported from *run*: *metadata* is the record's,
    *logs* its entries by writer (None: load them), *commit* the source
    commit's changes. True when something was written."""
    tags = run.get("tags")
    wrote = False
    entries = (storage.load_merged_log(app_name, verstr) if logs is None
               else [entry for writer_entries in logs.values() for entry in writer_entries])
    if needs_features(entries, commit):
        entry = features_entry(tags, commit, branch=not metadata.get("branch"))
        append_to_log(storage, app_name, verstr, {"timestamp": now_iso(), **entry})
        flush_log(storage, app_name, verstr)
        wrote = True
    note = tag(tags, NOTE)
    if note and not (metadata.get("note") or "").strip():
        storage.update_metadata(app_name, verstr, {"note": note})
        wrote = True
    return wrote
