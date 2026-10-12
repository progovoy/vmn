#!/usr/bin/env python3
"""Experiment diff for the vmn-exp ui API: metric delta + real tree diff text.

A tree diff materializes both runs into temp dirs and shells out to git — the
most expensive read the API has. :data:`DIFF_CACHE` answers a repeated pair
from memory (keyed by the records' diff hashes, so a changed record is diffed
again), lets at most two diffs run at once, and the text is capped.
"""
import threading
from types import SimpleNamespace

from vmn_exp.snapshot import _resolve_verstr, render_tree_diff
from vmn_exp.core.fold import fold_definitions, fold_log, fold_metrics, fold_values
from vmn_exp.core.log import load_log
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.resolve_ref import RefError
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import experiment_storage

MAX_DIFF_BYTES = 2 * 1024 * 1024
NO_BASE_COMMIT = "tree diff unavailable: {} has no base commit"


class DiffBusy(Exception):
    """Every diff slot stayed taken for the whole wait."""


class DiffMaterializeError(Exception):
    """The diff could not be produced because code could not be materialised."""

    def __init__(self, detail, reason="restore_failed"):
        super().__init__(detail)
        self.detail = detail
        self.reason = reason


class DiffCache:
    """Small LRU of diff results plus a gate on concurrent computations."""

    def __init__(self, size=32, concurrency=2, wait_sec=10.0):
        self._entries = LRU(size)
        self.slots = threading.BoundedSemaphore(concurrency)
        self.wait_sec = wait_sec

    def clear(self):
        self._entries.clear()

    def run(self, key, compute):
        """``compute()``'s ``(result, err)``, cached when it succeeded."""
        return self._entries.get(
            key, lambda: self._gated(compute), store=lambda answer: answer[1] is None
        )

    def _gated(self, compute):
        if not self.slots.acquire(timeout=self.wait_sec):
            raise DiffBusy()
        try:
            return compute()
        finally:
            self.slots.release()


DIFF_CACHE = DiffCache()


def _resolve_pair(storage, app_name, ref1, ref2):
    resolved = []
    for ref in (ref1, ref2):
        verstr, err = _resolve_verstr(storage, app_name, ref, kind="experiment")
        if err:
            return None, err
        resolved.append(verstr)
    return resolved, None


def _record_key(storage, app_name, verstr):
    meta = storage.load_metadata(app_name, verstr) or {}
    return verstr, meta.get("diff_hash"), meta.get("base_commit"), meta.get("timestamp")


def _fold_side(log, schema):
    """Fold a log and return ``(metrics, params, metric_summary, run_defs)``."""
    fold = fold_log(log)
    metrics, metric_summary = fold_metrics(fold, schema)
    params = fold_values(fold, "params")
    run_defs = fold_definitions(fold) if fold.get("metric_defs") else {}
    return metrics, params, metric_summary, run_defs


def _load_sides(storage, app_name, verstrs, read_log, schema=None):
    sides = []
    for verstr in verstrs:
        meta, patches = storage.load(app_name, verstr)
        if meta is None:
            return None, RefError(f"Experiment {verstr} not found")
        log = read_log(storage, app_name, verstr)
        metrics, params, metric_summary, run_defs = _fold_side(log, schema)
        sides.append((meta, patches, metrics, params, metric_summary, run_defs))
    return sides, None


def _is_param_only(key, params, metric_summary):
    """True when *key* came from a numeric param, not a ``metrics`` entry."""
    return key in params and key not in metric_summary


def _resolve_goal(key, run_defs1, run_defs2, schema):
    """The goal of *key*: the runs' own definitions first, then the schema."""
    return (
        metric_goal(run_defs1, key)
        or metric_goal(run_defs2, key)
        or metric_goal(schema, key)
    )


def _metrics_delta(m1, m2, side1_extra, side2_extra, schema=None):
    params1, ms1, defs1 = side1_extra
    params2, ms2, defs2 = side2_extra
    delta = {}
    for key in sorted(set(m1) | set(m2)):
        if m1.get(key) == m2.get(key):
            continue
        is_param = (
            _is_param_only(key, params1, ms1)
            and _is_param_only(key, params2, ms2)
        )
        goal = None if is_param else _resolve_goal(key, defs1, defs2, schema)
        delta[key] = {
            "from": m1.get(key),
            "to": m2.get(key),
            "goal": goal,
            "param": is_param,
        }
    return delta


def _truncated(text):
    """``(text, truncated)`` with *text* cut at a line to fit the cap."""
    data = text.encode("utf-8")
    if len(data) <= MAX_DIFF_BYTES:
        return text, False
    cut = data.rfind(b"\n", 0, MAX_DIFF_BYTES) + 1
    return data[:cut].decode("utf-8", "ignore"), True


_MATERIALIZE_REASONS = {
    "Failed to materialize snapshots for diff": "code_missing",
    "git diff could not be run": "restore_failed",
}


def _materialize_reason(err_msg):
    """Return a structured reason if *err_msg* is a materialisation failure."""
    for prefix, reason in _MATERIALIZE_REASONS.items():
        if err_msg and err_msg.startswith(prefix):
            return reason
    if err_msg and err_msg.startswith("git diff failed:"):
        return "restore_failed"
    return None


def _tree_diff(root_path, app_name, v1, side1, v2, side2):
    """``(fields, err)`` — the ``diff`` text (capped), or why there is none."""
    for verstr, side in ((v1, side1), (v2, side2)):
        if not side[0].get("base_commit"):
            return {"diff": None, "truncated": False,
                    "diff_unavailable": NO_BASE_COMMIT.format(verstr)}, None
    # Materialization only needs a root path (both sides have base_commit).
    vcs_stub = SimpleNamespace(vmn_root_path=root_path, name=app_name)
    text, err = render_tree_diff(vcs_stub, v1, side1[0], side1[1], v2, side2[0], side2[1])
    if err:
        reason = _materialize_reason(err)
        if reason:
            raise DiffMaterializeError(err, reason)
        return None, err
    text, truncated = _truncated(text)
    return {"diff": text, "truncated": truncated}, None


def _delta_from_sides(side1, side2, schema=None):
    """Build the ``metrics_delta`` dict from two loaded sides."""
    # side = (meta, patches, metrics, params, metric_summary, run_defs)
    return _metrics_delta(
        side1[2], side2[2],
        (side1[3], side1[4], side1[5]),
        (side2[3], side2[4], side2[5]),
        schema,
    )


def experiment_diff(root_path, app_name, ref1, ref2, schema=None):
    """Compare two experiments. Returns (result, error_message_or_None)."""
    storage = experiment_storage(root_path)
    verstrs, err = _resolve_pair(storage, app_name, ref1, ref2)
    if err:
        return None, err
    sides, err = _load_sides(storage, app_name, verstrs, load_log, schema)
    if err:
        return None, err
    (v1, v2), (side1, side2) = verstrs, sides
    tree, err = _tree_diff(root_path, app_name, v1, side1, v2, side2)
    if err:
        return None, err
    result = {
        "from_verstr": v1,
        "to_verstr": v2,
        "metrics_delta": _delta_from_sides(side1, side2, schema),
    }
    result.update(tree)
    return result, None


def cached_experiment_diff(root_path, app_name, ref1, ref2, schema=None):
    """:func:`experiment_diff` through :data:`DIFF_CACHE` (may raise DiffBusy)."""
    storage = experiment_storage(root_path)
    verstrs, err = _resolve_pair(storage, app_name, ref1, ref2)
    if err:
        return None, err
    key = (root_path, app_name) + tuple(_record_key(storage, app_name, v) for v in verstrs)
    return DIFF_CACHE.run(
        key, lambda: experiment_diff(root_path, app_name, *verstrs, schema=schema)
    )


def _merged_log(storage, app_name, verstr):
    if hasattr(storage, "load_merged_log"):
        return storage.load_merged_log(app_name, verstr)
    return load_log(storage, app_name, verstr)


def experiment_diff_from_storage(storage, app_name, ref1, ref2, schema=None):
    """Compare two experiments from a storage backend (S3). Metrics-only
    comparison: tree diffs are unavailable without a local checkout."""
    verstrs, err = _resolve_pair(storage, app_name, ref1, ref2)
    if err:
        return None, err
    sides, err = _load_sides(storage, app_name, verstrs, _merged_log, schema)
    if err:
        return None, err
    return {
        "from_verstr": verstrs[0],
        "to_verstr": verstrs[1],
        "metrics_delta": _delta_from_sides(sides[0], sides[1], schema),
        "diff": None,  # Tree diffs unavailable for S3 workspaces
        "truncated": False,
    }, None
