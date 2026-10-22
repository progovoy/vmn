#!/usr/bin/env python3
"""An outer run's subtree read straight from storage through its child
markers (:mod:`vmn_exp.storage.child_markers`) — for a scope whose runs the
index has not loaded yet (a 46k-run store's cold load takes tens of minutes).

Wave by wave: each run of a level costs its ``metadata.yml``, its
``run_state.yml`` and, above *max_depth*, one listing of its markers, all
issued concurrently (at most :data:`WORKERS` in flight). A flat outer run of
N children is two waves: ``3`` requests, then ``3 N`` (``2 N`` with
``max_depth=1``). Never a listing of the app's records.

The rows are the index's lean rows of the metadata alone
(:func:`~vmn_exp.core.index_views.lean_row` over an empty fold): ``idx``
is None (the storage index needs the full listing) and what the log and
metric objects hold is missing — ``params``, ``metrics``, ``tags``,
``inputs``, ``author``, ``has_intent`` (False), ``last_metric_at``, and
the side tables (metric summaries, outputs, features). Status comes from
the run states (:func:`~vmn_exp.core.tree.annotate_rows`), without the
store write time of ``run_state.yml`` (stuck detection uses the heartbeat
alone). A marker whose run is gone, or whose run names another parent, is
skipped.
"""
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.core.fold import new_fold
from vmn_exp.core.index_views import lean_row
from vmn_exp.core.status import load_run_state
from vmn_exp.storage.thread_context import in_caller_context

WORKERS = 32
MAX_DEPTH = 4

Subtree = namedtuple("Subtree", "rows run_states truncated")


def subtree_rows_direct(storage, app_name, verstr, limit=None, max_depth=MAX_DEPTH):
    """:class:`Subtree` ``(rows, run_states, truncated)`` of *verstr* and up
    to *limit* descendants (*max_depth* levels down); *truncated* when the
    limit cut some off. Rows: *verstr* first, then by timestamp."""
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="vmn-subtree-read") as pool:
        reader = _Reader(storage, app_name, pool)
        found, truncated = reader.walk(verstr, limit, max_depth)
    if found:
        found[1:] = sorted(found[1:], key=lambda f: (f[0].get("timestamp") or "",
                                                     f[0]["verstr"]))
    rows = [lean_row(None, meta, new_fold())[0] for meta, _ in found]
    return Subtree(rows, {meta["verstr"]: state for meta, state in found}, truncated)


class _Reader:
    def __init__(self, storage, app_name, pool):
        self._storage, self._app, self._pool = storage, app_name, pool

    def walk(self, verstr, limit, max_depth):
        """``([(metadata, run state)], truncated)``, the root first."""
        found, seen, truncated = [], {verstr}, False
        level, depth = [(verstr, None)], 0
        while level:
            listing = depth < max_depth
            nodes = self._read_level(level, listing)
            level = []
            for meta, state, kids in nodes:
                found.append((meta, state))
                for kid in kids:
                    if kid in seen:
                        continue
                    if limit is not None and len(seen) - 1 >= limit:
                        truncated = True
                        break
                    seen.add(kid)
                    level.append((kid, meta["verstr"]))
            depth += 1
        return found, truncated

    def _read_level(self, level, listing):
        """``[(metadata, run state, child markers)]`` of the *level*'s
        ``(verstr, expected parent)`` that exist, every read in flight at once."""
        submit = self._pool.submit
        load_metadata = in_caller_context(self._storage.load_metadata)
        run_state = in_caller_context(load_run_state)
        list_children = in_caller_context(self._storage.list_children)
        reads = [
            (parent,
             submit(load_metadata, self._app, v),
             submit(run_state, self._storage, self._app, v),
             submit(list_children, self._app, v) if listing else None)
            for v, parent in level
        ]
        nodes = []
        for parent, meta, state, kids in reads:
            meta = meta.result()
            if meta is None or (parent is not None and meta.get("parent") != parent):
                continue
            nodes.append((meta, state.result(), kids.result() if kids else []))
        return nodes
