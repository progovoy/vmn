#!/usr/bin/env python3
"""The reads of ``vmn-exp prune -v <ref>``: the named runs alone.

A targeted prune never builds the experiment index nor lists the app's
runs: an exact verstr resolves as it is (a prefix or ``@N`` resolves through
:func:`~vmn_exp.core.refs.resolve_experiment`, which may need a listing),
each target's ``metadata.yml`` — and, for ``--protect-tag``, its log — is
read directly, and whether a target has a surviving child comes from its
own child markers (:mod:`vmn_exp.storage.child_markers`). A child recorded
without a marker is not seen: ``vmn-exp backfill-children`` writes them.
"""
from vmn_exp.cli.prune_guards import map_storage
from vmn_exp.core.children import parent_of
from vmn_exp.core.fold import fold_log, fold_tags
from vmn_exp.core.log import load_log
from vmn_exp.core.refs import resolve_experiment


def targeted_metas(storage, app_name, refs, with_tags=False):
    """``(metas, None)`` of the runs *refs* name, in order and once each —
    with their current ``tags`` when *with_tags* — or ``(None, error)`` for
    the first ref that names no run."""
    metas, seen = [], set()
    for ref in refs:
        verstr, err = resolve_experiment(storage, app_name, ref)
        if err:
            return None, err
        if verstr in seen:
            continue
        meta = storage.load_metadata(app_name, verstr)
        if meta is None:
            return None, f"Experiment '{verstr}' not found for {app_name}"
        seen.add(verstr)
        metas.append(dict(meta, verstr=verstr))
    if with_tags:
        tags = map_storage(storage, lambda m: _tags(storage, app_name, m["verstr"]), metas)
        for meta, run_tags in zip(metas, tags):
            meta["tags"] = run_tags
    return metas, None


def _tags(storage, app_name, verstr):
    return fold_tags(fold_log(load_log(storage, app_name, verstr)))


def _children(storage, app_name, verstr):
    """The existing runs whose ``parent`` is *verstr*, by its markers."""
    marked = getattr(storage, "list_children", None)
    kids = marked(app_name, verstr) if marked else []
    return [k for k in kids if parent_of(storage.load_metadata(app_name, k)) == verstr]


def without_kept_parents(storage, app_name, doomed):
    """*doomed* (verstrs) less every run with a child that survives — one not
    doomed, or one kept for that same reason."""
    doomed = set(doomed)
    order = sorted(doomed)
    kids = dict(zip(order, map_storage(
        storage, lambda v: _children(storage, app_name, v), order)))
    while True:
        kept = {v for v in doomed if any(k not in doomed for k in kids[v])}
        if not kept:
            return doomed
        doomed -= kept
