#!/usr/bin/env python3
"""``vmn-exp prune``: delete old experiments without breaking live runs or trees.

Selection proposes candidates, either by policy (``--keep N`` / ``--older-than``)
or, with ``-v <ref>`` (repeatable — a verstr, a unique prefix or ``@N``), by
naming the exact run(s) to delete. Either way, guards then take runs back out
of the list:

* a run whose derived status is ``running`` or ``stuck`` is never deleted
  (``--force`` overrides) — a stuck run may just have a late heartbeat, and a
  live one would otherwise recreate a half-empty directory;
* a run carrying a ``--protect-tag`` key is never deleted (``--force``
  overrides), so a run someone tagged ``stage=prod`` survives a bulk prune —
  and a ``-v`` targeting it directly, for the same reason;
* a run with a kept descendant is kept, so no surviving run points at a parent
  that no longer exists.

A code object (:mod:`vmn_exp.core.code_store`) is deleted with the last run of
its code.
"""
import datetime
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.cli.prune_query import print_preview, query_candidates
from vmn_exp.cli.views import metrics_schema
from vmn_exp.core.code_store import drop_unused_code
from vmn_exp.reports import comments
from vmn_exp.core.index import indexed_snapshot
from vmn_exp.core.query import QueryError
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.core.status import (
    RUNNING,
    STUCK,
    derive_status,
    load_run_state,
    parse_iso,
    run_state_observed_at,
)
from version_stamp.api import VMN_LOGGER

# Remote reads/deletes in flight at once; a delete fans out further inside S3.
_REMOTE_WORKERS = 4
_LIVE = (RUNNING, STUCK)


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


def _delete_run(storage, app_name, verstr):
    storage.delete(app_name, verstr)
    if hasattr(storage, "in_area"):
        comments.delete_thread(storage, ("run", app_name, verstr))


def _map(storage, fn, items):
    """``[fn(item)]`` in order — concurrently when each call goes over the
    network, so 10k remote runs are not 10k serial round trips."""
    if len(items) < 2 or not storage.is_remote():
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=_REMOTE_WORKERS) as pool:
        return list(pool.map(fn, items))


def _read_state(storage, app_name, verstr):
    """``(run state, its store write time)`` straight from storage."""
    return (
        load_run_state(storage, app_name, verstr),
        run_state_observed_at(storage, app_name, verstr),
    )


def _live_runs(storage, app_name, candidates, snapshot=None):
    """``{verstr: status}`` of the *candidates* that may still be running.

    The index *snapshot* supplies run states and their store write times when
    there is one; else each candidate's are read from storage.
    """
    verstrs = [m["verstr"] for m in candidates]
    if snapshot is None:
        read = lambda v: _read_state(storage, app_name, v)  # noqa: E731
        states = _map(storage, read, verstrs)
    else:
        observed = snapshot.run_state_observed_at
        states = [(snapshot.run_states.get(v), observed.get(v)) for v in verstrs]
    statuses = zip(
        verstrs, (derive_status(state, observed_at=at) for state, at in states)
    )
    return {v: status for v, status in statuses if status in _LIVE}


def _tag_protected(candidates, protect_tags):
    """``{verstr: matched tag name}`` of *candidates* carrying any of
    *protect_tags* — a run's own current tags, so a removed tag never
    protects it."""
    if not protect_tags:
        return {}
    protect = set(protect_tags)
    protected = {}
    for meta in candidates:
        hit = protect & set((meta.get("tags") or {}).keys())
        if hit:
            protected[meta["verstr"]] = sorted(hit)[0]
    return protected


def _apply_guards(
    storage, app_name, metas, candidates, force, protect_tags=None, snapshot=None,
    reg_protected=None,
):
    """Split *candidates* into (delete, {skipped live verstr: status},
    {skipped tag-protected verstr: tag name}, {registry-protected verstr: reason})."""
    live = {} if force else _live_runs(storage, app_name, candidates, snapshot)
    protected = {} if force else _tag_protected(candidates, protect_tags)
    reg = reg_protected or {}

    doomed = {m["verstr"] for m in candidates} - set(live) - set(protected) - set(reg)
    parent_of = {m["verstr"]: m.get("parent") for m in metas if m.get("parent")}
    for meta in metas:
        if meta["verstr"] not in doomed:
            doomed -= _ancestors(meta["verstr"], parent_of)
    return [m for m in candidates if m["verstr"] in doomed], live, protected, reg


def _skip_message(verstr, status):
    if status == STUCK:
        return (
            f"Skipping {verstr}: stuck (its heartbeat is late; it may still be "
            "running — use --force to delete it)"
        )
    return f"Skipping {verstr}: still running (use --force to delete it)"


def _tag_skip_message(verstr, tag_name):
    return (
        f"Skipping {verstr}: protected by tag '{tag_name}' "
        "(use --force to delete it)"
    )


def _registry_protected(storage, app_name, candidates):
    """Return ``{verstr: reason}`` for candidates referenced by a non-deleted
    model version.  Never overridable by ``--force``.

    Raises any exception from the registry — callers must catch and fail closed.
    Only called when *storage* exposes ``list_record_names`` (the registry
    interface); storages without it are treated as having no registry.
    """
    if not candidates or not hasattr(storage, "list_record_names"):
        return {}
    import vmn_exp.registry.view as _rv  # lazy: keeps stamping paths clean
    refs = _rv.registered_runs(storage)
    _REASON = "registered as a model version; use `vmn-exp model delete` first"
    return {
        m["verstr"]: _REASON
        for m in candidates
        if (app_name, m["verstr"]) in refs
    }


def _local_view(storage):
    """The local half of a local+remote storage (``--local-only``)."""
    return getattr(storage, "_local", None) or storage


def _metas_and_snapshot(storage, app_name):
    """``(metas oldest first, index snapshot or None)`` — through the experiment
    index when the storage can be indexed, so selecting among 10k runs does not
    read every record's metadata and run state; directly otherwise."""
    if hasattr(storage, "list_files"):
        snapshot = indexed_snapshot(storage, app_name, wait=True, fallback=None)
        if snapshot is not None:
            metas = [
                {"verstr": r["verstr"], "timestamp": r.get("timestamp"),
                 "parent": r.get("parent"), "tags": r.get("tags") or {},
                 "code_verstr": r.get("code_verstr")}
                for r in snapshot.rows
            ]
            return metas, snapshot
    return storage.list_snapshots(app_name), None


def _targeted_candidates(storage, app_name, metas, snapshot, refs):
    """The subset of *metas* named by *refs*, or (None, error) for the first
    ref that does not resolve to an existing run."""
    by_verstr = {m["verstr"]: m for m in metas}
    candidates = []
    for ref in refs:
        verstr, err = resolve_experiment(storage, app_name, ref, snapshot=snapshot)
        if err:
            return None, err
        meta = by_verstr.get(verstr)
        if meta is None:
            return None, f"Experiment '{verstr}' not found for {app_name}"
        candidates.append(meta)
    return candidates, None


def _select_candidates(storage, app_name, metas, snapshot, args, schema=None):
    """Return ``(candidates, error_code)`` according to the selection flags.

    *error_code* is non-None when the caller should return it immediately.
    *candidates* is None when the function already printed a "nothing to do"
    message and the caller should return 0.
    """
    keep = getattr(args, "keep", None)
    older_than = getattr(args, "older_than", None)
    refs = getattr(args, "version", None)
    query = getattr(args, "query", None)

    if query is not None:
        if refs:
            VMN_LOGGER.error(
                "--query cannot be combined with -v: use one or the other"
            )
            return None, 1
        try:
            candidates = query_candidates(storage, app_name, metas, query, schema)
        except QueryError as e:
            VMN_LOGGER.error(f"Invalid --query: {e}")
            return None, 1
        # --keep / --older-than refine within the query scope
        if keep is not None or older_than is not None:
            if keep is not None and keep >= len(candidates):
                print(
                    f"Only {len(candidates)} matching experiments, "
                    f"nothing to prune (--keep {keep})"
                )
                return None, None
            try:
                candidates = _candidates(candidates, keep, older_than)
            except ValueError as e:
                VMN_LOGGER.error(str(e))
                return None, 1
        return candidates, None

    if refs:
        if keep is not None or older_than is not None:
            VMN_LOGGER.error(
                "-v cannot be combined with --keep/--older-than: prune either "
                "a specific run or by policy, not both"
            )
            return None, 1
        candidates, err = _targeted_candidates(storage, app_name, metas, snapshot, refs)
        if err:
            VMN_LOGGER.error(err)
            return None, 1
        return candidates, None

    if keep is None and older_than is None:
        VMN_LOGGER.error("Specify --keep N or --older-than Xd (or -v <ref>)")
        return None, 1
    if keep is not None and 0 < len(metas) <= keep:
        print(f"Only {len(metas)} experiments, nothing to prune (--keep {keep})")
        return None, None
    try:
        candidates = _candidates(metas, keep, older_than)
    except ValueError as e:
        VMN_LOGGER.error(str(e))
        return None, 1
    return candidates, None


def experiment_prune(vcs, params, storage, args, app_name):
    if getattr(args, "local_only", False):
        storage = _local_view(storage)
    metas, snapshot = _metas_and_snapshot(storage, app_name)
    if not metas:
        print("No experiments to prune")
        return 0

    candidates, rc = _select_candidates(
        storage, app_name, metas, snapshot, args, metrics_schema(vcs)
    )
    if rc is not None:
        return rc
    if candidates is None:
        return 0

    try:
        reg_protected = _registry_protected(storage, app_name, candidates)
    except Exception as e:
        VMN_LOGGER.error(
            f"Cannot read model registry: {e}. Refusing to prune."
        )
        return 1

    to_delete, live, protected, reg = _apply_guards(
        storage,
        app_name,
        metas,
        candidates,
        force=getattr(args, "force", False),
        protect_tags=getattr(args, "protect_tag", None),
        snapshot=snapshot,
        reg_protected=reg_protected,
    )
    for verstr in sorted(live):
        print(_skip_message(verstr, live[verstr]))
    for verstr in sorted(protected):
        print(_tag_skip_message(verstr, protected[verstr]))
    for verstr in sorted(reg):
        print(f"Skipping {verstr}: {reg[verstr]}")
    if not to_delete:
        print("Nothing to prune")
        return 0

    query = getattr(args, "query", None)
    dry_run = getattr(args, "dry_run", False) or (
        query is not None and not getattr(args, "yes", False)
    )
    if dry_run:
        if query is not None:
            print_preview(to_delete)
        else:
            print(f"Would delete {len(to_delete)} experiments:")
            for meta in to_delete:
                print(f"  {meta['verstr']}")
        return 0

    verstrs = [m["verstr"] for m in to_delete]
    _map(storage, lambda v: _delete_run(storage, app_name, v), verstrs)
    drop_unused_code(storage, app_name, {m.get("code_verstr") for m in to_delete})
    for verstr in verstrs:
        print(f"Deleted {verstr}")
    print(f"Pruned {len(to_delete)} experiments, kept {len(metas) - len(to_delete)}")
    return 0
