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
from vmn_exp._base import valid_path_component
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


def _children(storage, app_name, doomed):
    """``{verstr: [existing runs whose parent is it]}`` for *doomed*, by their
    child markers; every marked child's metadata is read in one map."""
    marked = getattr(storage, "list_children", None)
    order = sorted(doomed)
    kids = map_storage(storage, lambda v: marked(app_name, v), order) if marked else []
    pairs = [(v, k) for v, ks in zip(order, kids) for k in ks]
    metas = map_storage(storage, lambda p: storage.load_metadata(app_name, p[1]), pairs)
    children = {v: [] for v in order}
    for (v, kid), meta in zip(pairs, metas):
        if parent_of(meta) == v:
            children[v].append(kid)
    return children


def without_kept_parents(storage, app_name, doomed):
    """*doomed* (verstrs) less every run with a child that survives — one not
    doomed, or one kept for that same reason."""
    doomed = set(doomed)
    kids = _children(storage, app_name, doomed)
    while True:
        kept = {v for v in doomed if any(k not in doomed for k in kids[v])}
        if not kept:
            return doomed
        doomed -= kept
