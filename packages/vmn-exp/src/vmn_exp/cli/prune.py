#!/usr/bin/env python3
"""``vmn-exp prune``: delete old experiments without breaking live runs or trees.

Selection proposes candidates, either by policy (``--keep N`` / ``--older-than``
/ ``--query``) or, with ``-v <ref>`` (repeatable — a verstr, a unique prefix
or ``@N``), by naming the exact run(s) to delete. Either way, guards
(:mod:`vmn_exp.cli.prune_guards`) then take runs back out of the list:

* a run whose derived status is ``running`` or ``stuck`` is never deleted
  (``--force`` overrides) — a stuck run may just have a late heartbeat, and a
  live one would otherwise recreate a half-empty directory;
* a run carrying a ``--protect-tag`` key is never deleted (``--force``
  overrides), so a run someone tagged ``stage=prod`` survives a bulk prune —
  and a ``-v`` targeting it directly, for the same reason;
* a run with a kept descendant is kept, so no surviving run points at a parent
  that no longer exists.

A policy prune selects through the experiment index; a targeted one reads its
targets alone (:mod:`vmn_exp.cli.prune_targeted`) — after one scan of the
app's parent links the first time, and on every prune of a backend without
child markers. A policy prune also trims
the change journal unless ``--no-trim-journal``; a targeted one never does.

A code object (:mod:`vmn_exp.core.code_store`) is deleted with the last run of
its code.
"""
import datetime
from functools import partial

from vmn_exp.cli.prune_guards import (
    registry_protected,
    skip_message,
    tag_protected,
    tag_skip_message,
)
from vmn_exp.cli.prune_query import print_preview, query_candidates
from vmn_exp.cli.prune_targeted import map_storage, targeted_metas, without_kept_parents
from vmn_exp.cli.views import metrics_schema
from vmn_exp.core.children import unmark_parent
from vmn_exp.core.code_store import drop_unused_code
from vmn_exp.core.index import indexed_snapshot
from vmn_exp.core.query import QueryError
from vmn_exp.reports import comments
from vmn_exp.core.status import (
    RUNNING,
    STUCK,
    derive_status,
    load_run_state,
    parse_iso,
    run_state_observed_at,
)
from vmn_exp.storage.journal import prune_journal
from version_stamp.api import VMN_LOGGER

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


def _delete_run(storage, app_name, meta):
    verstr = meta["verstr"]
    storage.delete(app_name, verstr)
    unmark_parent(storage, app_name, meta)
    if hasattr(storage, "in_area"):
        comments.delete_thread(storage, ("run", app_name, verstr))


def _read_state(storage, app_name, verstr):
    """``(run state, its store write time)`` straight from storage."""
    return (
        load_run_state(storage, app_name, verstr),
        run_state_observed_at(storage, app_name, verstr),
    )


def _live_runs(storage, app_name, candidates, snapshot):
    """``{verstr: status}`` of the *candidates* that may still be running.

    The index *snapshot* supplies run states and their store write times when
    there is one; else each candidate's are read from storage.
    """
    verstrs = [m["verstr"] for m in candidates]
    if snapshot is None:
        read = lambda v: _read_state(storage, app_name, v)  # noqa: E731
        states = map_storage(storage, read, verstrs)
    else:
        observed = snapshot.run_state_observed_at
        states = [(snapshot.run_states.get(v), observed.get(v)) for v in verstrs]
    statuses = zip(
        verstrs, (derive_status(state, observed_at=at) for state, at in states)
    )
    return {v: status for v, status in statuses if status in _LIVE}


def _apply_guards(storage, app_name, candidates, args, reg, snapshot, keep_parents):
    """``(delete, {skipped live verstr: status}, {skipped tag-protected
    verstr: tag name})``: *candidates* less the live, tag-protected and
    registry-protected (*reg*) ones, less those *keep_parents* (doomed
    verstrs → the ones that may go) keeps for a surviving child."""
    force = getattr(args, "force", False)
    live = {} if force else _live_runs(storage, app_name, candidates, snapshot)
    protect_tags = getattr(args, "protect_tag", None)
    protected = {} if force else tag_protected(candidates, protect_tags)
    doomed = {m["verstr"] for m in candidates} - set(live) - set(protected) - set(reg)
    doomed = keep_parents(doomed)
    return [m for m in candidates if m["verstr"] in doomed], live, protected


def _without_kept_ancestors(metas, doomed):
    """*doomed* less every ancestor of a run in *metas* that is not doomed."""
    parent_of = {m["verstr"]: m.get("parent") for m in metas if m.get("parent")}
    for meta in metas:
        if meta["verstr"] not in doomed:
            doomed -= _ancestors(meta["verstr"], parent_of)
    return doomed


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


def _refuse_mixed_selection(args):
    """1 (after logging why) when ``-v`` is combined with a policy flag."""
    if not getattr(args, "version", None):
        return None
    if getattr(args, "query", None) is not None:
        VMN_LOGGER.error("--query cannot be combined with -v: use one or the other")
        return 1
    if getattr(args, "keep", None) is not None or getattr(args, "older_than", None) is not None:
        VMN_LOGGER.error(
            "-v cannot be combined with --keep/--older-than: prune either "
            "a specific run or by policy, not both"
        )
        return 1
    return None


def _select_candidates(storage, app_name, metas, args, schema):
    """Return ``(candidates, error_code)`` according to the policy flags.

    *error_code* is non-None when the caller should return it immediately.
    *candidates* is None when the function already printed a "nothing to do"
    message and the caller should return 0.
    """
    keep = getattr(args, "keep", None)
    older_than = getattr(args, "older_than", None)
    query = getattr(args, "query", None)

    if query is None:
        scope, noun = metas, "experiments"
    else:
        try:
            scope = query_candidates(storage, app_name, metas, query, schema)
        except QueryError as e:
            VMN_LOGGER.error(f"Invalid --query: {e}")
            return None, 1
        noun = "matching experiments"

    if keep is None and older_than is None:
        if query is None:
            VMN_LOGGER.error("Specify --keep N or --older-than Xd (or -v <ref>)")
            return None, 1
        return scope, None
    # --keep / --older-than refine within the query scope, if any
    if keep is not None and keep >= len(scope):
        print(f"Only {len(scope)} {noun}, nothing to prune (--keep {keep})")
        return None, None
    try:
        return _candidates(scope, keep, older_than), None
    except ValueError as e:
        VMN_LOGGER.error(str(e))
        return None, 1


def _is_dry_run(args):
    return getattr(args, "dry_run", False) or (
        getattr(args, "query", None) is not None and not getattr(args, "yes", False)
    )


def _trim_journal(storage):
    """Drop journal partitions past their use (stores without a lifecycle rule)."""
    try:
        prune_journal(storage)
    except Exception as e:
        VMN_LOGGER.warning(f"Could not trim the change journal: {e}")


def _read_registry(storage, app_name, candidates):
    """``(registry-protected, None)``, or ``(None, 1)`` when the registry
    cannot be read — a prune then deletes nothing."""
    try:
        return registry_protected(storage, app_name, candidates), None
    except Exception as e:
        VMN_LOGGER.error(f"Cannot read model registry: {e}. Refusing to prune.")
        return None, 1


def experiment_prune(vcs, params, storage, args, app_name):
    if getattr(args, "local_only", False):
        storage = _local_view(storage)
    rc = _refuse_mixed_selection(args)
    if rc is not None:
        return rc
    if getattr(args, "version", None):
        return _prune_targeted(storage, app_name, args)
    return _prune_by_policy(vcs, storage, app_name, args)


def _prune_targeted(storage, app_name, args):
    with_tags = not getattr(args, "force", False) and bool(getattr(args, "protect_tag", None))
    metas, err = targeted_metas(storage, app_name, args.version, with_tags)
    if err:
        VMN_LOGGER.error(err)
        return 1
    reg, rc = _read_registry(storage, app_name, metas)
    if rc is not None:
        return rc
    to_delete, live, protected = _apply_guards(
        storage, app_name, metas, args, reg, None, _targeted_keep_parents(storage, app_name, args))
    return _finish(storage, app_name, args, to_delete, (live, protected, reg))


def _targeted_keep_parents(storage, app_name, args):
    """The surviving-child guard of a targeted prune: by child markers, or —
    on a backend without them — from every run's parent."""
    if storage.has_child_markers:
        return partial(without_kept_parents, storage, app_name, dry_run=_is_dry_run(args))
    return partial(_without_kept_ancestors, _metas_and_snapshot(storage, app_name)[0])


def _prune_by_policy(vcs, storage, app_name, args):
    if not _is_dry_run(args) and not getattr(args, "no_trim_journal", False):
        _trim_journal(storage)
    metas, snapshot = _metas_and_snapshot(storage, app_name)
    if not metas:
        print("No experiments to prune")
        return 0

    candidates, rc = _select_candidates(
        storage, app_name, metas, args, metrics_schema(vcs, storage, app_name)
    )
    if rc is not None:
        return rc
    if candidates is None:
        return 0

    reg, rc = _read_registry(storage, app_name, candidates)
    if rc is not None:
        return rc

    to_delete, live, protected = _apply_guards(
        storage, app_name, candidates, args, reg, snapshot,
        partial(_without_kept_ancestors, metas))
    return _finish(storage, app_name, args, to_delete, (live, protected, reg),
                   total=len(metas))


def _print_skipped(live, protected, reg):
    for verstr in sorted(live):
        print(skip_message(verstr, live[verstr]))
    for verstr in sorted(protected):
        print(tag_skip_message(verstr, protected[verstr]))
    for verstr in sorted(reg):
        print(f"Skipping {verstr}: {reg[verstr]}")


def _finish(storage, app_name, args, to_delete, skipped, total=None):
    """Report the *skipped* runs, then preview or delete *to_delete*."""
    _print_skipped(*skipped)
    if not to_delete:
        print("Nothing to prune")
        return 0

    if _is_dry_run(args):
        if getattr(args, "query", None) is not None:
            print_preview(f"Would delete {len(to_delete)} experiments:",
                          [meta["verstr"] for meta in to_delete])
        else:
            print(f"Would delete {len(to_delete)} experiments:")
            for meta in to_delete:
                print(f"  {meta['verstr']}")
        return 0

    map_storage(storage, lambda m: _delete_run(storage, app_name, m), to_delete)
    drop_unused_code(storage, app_name, {m.get("code_verstr") for m in to_delete})
    for meta in to_delete:
        print(f"Deleted {meta['verstr']}")
    kept = "" if total is None else f", kept {total - len(to_delete)}"
    print(f"Pruned {len(to_delete)} experiments{kept}")
    return 0
