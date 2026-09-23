#!/usr/bin/env python3
"""``vmn exp prune``: delete old experiments without breaking live runs or trees.

Selection (``--keep N`` / ``--older-than``) proposes candidates; two guards then
take runs back out of the list:

* a run whose derived status is ``running`` is never deleted (``--force``
  overrides) — its heartbeat would otherwise recreate a half-empty directory;
* a run with a kept descendant is kept, so no surviving run points at a parent
  that no longer exists.
"""
import datetime

from version_stamp.core.experiment_status import (
    RUNNING,
    derive_status,
    load_run_state,
    parse_iso,
)
from version_stamp.core.logging import VMN_LOGGER


def _parse_duration(duration_str):
    """Parse '30d', '2w', '24h' to timedelta."""
    s = duration_str.strip().lower()
    if s.endswith("d"):
        return datetime.timedelta(days=int(s[:-1]))
    if s.endswith("w"):
        return datetime.timedelta(weeks=int(s[:-1]))
    if s.endswith("h"):
        return datetime.timedelta(hours=int(s[:-1]))
    raise ValueError(f"Invalid duration: {duration_str}. Use Nd, Nw, or Nh.")


def _older_than(metas, older_than):
    cutoff = datetime.datetime.now(datetime.timezone.utc) - _parse_duration(older_than)
    return [m for m in metas if (parse_iso(m.get("timestamp")) or cutoff) < cutoff]


def _candidates(metas, keep, older_than):
    """Metas the selection flags propose deleting, oldest first."""
    if keep is not None:
        return list(metas) if keep == 0 else list(metas[:-keep])
    return _older_than(metas, older_than)


def _ancestors(verstr, parent_of):
    seen = set()
    parent = parent_of.get(verstr)
    while parent and parent not in seen:
        seen.add(parent)
        parent = parent_of.get(parent)
    return seen


def _apply_guards(storage, app_name, metas, candidates, force):
    """Split *candidates* into (delete, skipped_running)."""
    running = set()
    if not force:
        for meta in candidates:
            state = load_run_state(storage, app_name, meta["verstr"])
            if derive_status(state) == RUNNING:
                running.add(meta["verstr"])

    doomed = {m["verstr"] for m in candidates} - running
    parent_of = {m["verstr"]: m.get("parent") for m in metas if m.get("parent")}
    for meta in metas:
        if meta["verstr"] not in doomed:
            doomed -= _ancestors(meta["verstr"], parent_of)
    return [m for m in candidates if m["verstr"] in doomed], sorted(running)


def _local_view(storage):
    """The local half of a local+remote storage (``--local-only``)."""
    return getattr(storage, "_local", None) or storage


def experiment_prune(vcs, params, storage, args, app_name):
    if getattr(args, "local_only", False):
        storage = _local_view(storage)
    metas = storage.list_snapshots(app_name)
    if not metas:
        print("No experiments to prune")
        return 0

    keep = getattr(args, "keep", None)
    older_than = getattr(args, "older_than", None)
    if keep is None and older_than is None:
        VMN_LOGGER.error("Specify --keep N or --older-than Xd")
        return 1
    if keep is not None and 0 < len(metas) <= keep:
        print(f"Only {len(metas)} experiments, nothing to prune (--keep {keep})")
        return 0
    try:
        candidates = _candidates(metas, keep, older_than)
    except ValueError as e:
        VMN_LOGGER.error(str(e))
        return 1

    to_delete, running = _apply_guards(
        storage, app_name, metas, candidates, getattr(args, "force", False)
    )
    for verstr in running:
        print(f"Skipping {verstr}: still running (use --force to delete it)")
    if not to_delete:
        print("Nothing to prune")
        return 0
    if getattr(args, "dry_run", False):
        print(f"Would delete {len(to_delete)} experiments:")
        for meta in to_delete:
            print(f"  {meta['verstr']}")
        return 0

    for meta in to_delete:
        storage.delete(app_name, meta["verstr"])
        print(f"Deleted {meta['verstr']}")
    print(f"Pruned {len(to_delete)} experiments, kept {len(metas) - len(to_delete)}")
    return 0
