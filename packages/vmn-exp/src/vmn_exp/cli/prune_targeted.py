#!/usr/bin/env python3
"""The reads of ``vmn-exp prune -v <ref>``: the named runs alone.

In its steady state a targeted prune never builds the experiment index
nor lists the app's runs: an exact verstr resolves as it is (a prefix or ``@N`` resolves through
:func:`~vmn_exp.core.refs.resolve_experiment`, which may need a listing),
each target's ``metadata.yml`` — and, for ``--protect-tag``, its log — is
read directly, and whether a target has a surviving child comes from its
own child markers (:mod:`vmn_exp.storage.child_markers`) once the app's
markers are known complete. Until then — a store older than the markers, or
one where a marker failed to write — the first targeted prune reads every
run's parent once, writes the missing markers and flags the app complete
(a dry run only reads); later ones read their targets alone. A backend
without markers (``has_child_markers`` false) is guarded by :mod:`prune`
from every run's parent instead.
"""
import sys
from functools import partial

from vmn_exp._base import valid_path_component
from vmn_exp.cli.backfill_children import scan_app
from vmn_exp.core.children import parent_of
from vmn_exp.core.log import current_tags, load_log
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.core.resolve_ref import LATEST_WORDS
from vmn_exp.storage.s3_base import parallel_map


def map_storage(storage, fn, items):
    """``[fn(item)]`` in order — concurrently, within the shared fan-out
    budget, when each call goes over the network, so 10k remote runs are not
    10k serial round trips."""
    if len(items) < 2 or not storage.is_remote():
        return [fn(item) for item in items]
    return parallel_map(fn, items)


def targeted_metas(storage, app_name, refs, with_tags=False):
    """``(metas, None)`` of the runs *refs* name, in order and once each —
    with their current ``tags`` when *with_tags* — or ``(None, error)`` for
    the first ref that names no run.

    A ref that can be a record name is read as one first, all at once; only
    the ones that name no record go through :func:`resolve_experiment`."""
    refs = list(dict.fromkeys(refs))
    exact = [ref for ref in refs if _may_be_verstr(ref)]
    direct = dict(zip(exact, map_storage(
        storage, lambda v: storage.load_metadata(app_name, v), exact)))
    metas, seen = [], set()
    for ref in refs:
        verstr, meta = ref, direct.get(ref)
        if meta is None:
            verstr, err = resolve_experiment(storage, app_name, ref)
            if err:
                return None, err
            if verstr not in seen and (verstr != ref or ref not in direct):
                meta = storage.load_metadata(app_name, verstr)
        if verstr in seen:
            continue
        if meta is None:
            return None, f"Experiment '{verstr}' not found for {app_name}"
        seen.add(verstr)
        metas.append(dict(meta, verstr=verstr))
    if with_tags:
        tags = map_storage(storage, lambda m: _tags(storage, app_name, m["verstr"]), metas)
        for meta, run_tags in zip(metas, tags):
            meta["tags"] = run_tags
    return metas, None


def _may_be_verstr(ref):
    return ref not in LATEST_WORDS and not ref.startswith("@") and valid_path_component(ref)


def _tags(storage, app_name, verstr):
    return current_tags(load_log(storage, app_name, verstr))


def _children(storage, app_name, doomed, dry_run):
    """``{verstr: [existing runs whose parent is it]}`` for *doomed*: by their
    child markers once the app's are known complete, else from one scan of
    every run's parent (:func:`~vmn_exp.cli.backfill_children.scan_app`)."""
    if storage.children_complete(app_name):
        return _marked_children(storage, app_name, doomed)
    notice = partial(_scan_notice, app_name, dry_run)
    by_parent = scan_app(storage, app_name, dry_run, notice)[1]
    return {v: by_parent.get(v, []) for v in doomed}


def _scan_notice(app_name, dry_run, total):
    if dry_run:
        print(f"Reading child links of {app_name} ({total} runs)", file=sys.stderr)
    else:
        print(f"Indexing child links of {app_name} once ({total} runs); "
              "later prunes read only their targets", file=sys.stderr)


def _marked_children(storage, app_name, doomed):
    """:func:`_children` by the markers; every marked child's metadata is
    read in one map."""
    order = sorted(doomed)
    kids = map_storage(storage, lambda v: storage.list_children(app_name, v), order)
    pairs = [(v, k) for v, ks in zip(order, kids) for k in ks]
    metas = map_storage(storage, lambda p: storage.load_metadata(app_name, p[1]), pairs)
    children = {v: [] for v in order}
    for (v, kid), meta in zip(pairs, metas):
        if parent_of(meta) == v:
            children[v].append(kid)
    return children


def without_kept_parents(storage, app_name, doomed, dry_run=False):
    """*doomed* (verstrs) less every run with a child that survives — one not
    doomed, or one kept for that same reason. A *dry_run* writes nothing."""
    doomed = set(doomed)
    kids = _children(storage, app_name, doomed, dry_run)
    while True:
        kept = {v for v in doomed if any(k not in doomed for k in kids[v])}
        if not kept:
            return doomed
        doomed -= kept
