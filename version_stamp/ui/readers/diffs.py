#!/usr/bin/env python3
"""Experiment diff for the vmn ui API: metric delta + real tree diff text.

A tree diff materializes both runs into temp dirs and shells out to git — the
most expensive read the API has. :data:`DIFF_CACHE` answers a repeated pair
from memory (keyed by the records' diff hashes, so a changed record is diffed
again), lets at most two diffs run at once, and the text is capped.
"""
import threading
from collections import OrderedDict
from types import SimpleNamespace

from version_stamp.cli.snapshot import _resolve_verstr, render_tree_diff
from version_stamp.core.experiment_log import latest_metrics, load_log
from version_stamp.ui.readers.experiments import experiment_storage
from version_stamp.ui.readers.snapshots import _load_metadata

MAX_DIFF_BYTES = 2 * 1024 * 1024
NO_BASE_COMMIT = "tree diff unavailable: {} has no base commit"


class DiffBusy(Exception):
    """Every diff slot stayed taken for the whole wait."""


class DiffCache:
    """Small LRU of diff results plus a gate on concurrent computations."""

    def __init__(self, size=32, concurrency=2, wait_sec=10.0):
        self._size = size
        self._entries = OrderedDict()
        self._lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(concurrency)
        self.wait_sec = wait_sec

    def clear(self):
        with self._lock:
            self._entries.clear()

    def run(self, key, compute):
        """``compute()``'s ``(result, err)``, cached when it succeeded."""
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
        if not self.slots.acquire(timeout=self.wait_sec):
            raise DiffBusy()
        try:
            answer = compute()
        finally:
            self.slots.release()
        if answer[1] is None:
            with self._lock:
                self._entries[key] = answer
                while len(self._entries) > self._size:
                    self._entries.popitem(last=False)
        return answer


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
    meta = _load_metadata(storage, app_name, verstr) or {}
    return verstr, meta.get("diff_hash"), meta.get("base_commit"), meta.get("timestamp")


def _load_sides(storage, app_name, verstrs, read_log):
    sides = []
    for verstr in verstrs:
        meta, patches = storage.load(app_name, verstr)
        if meta is None:
            return None, f"Experiment {verstr} not found"
        sides.append((meta, patches, latest_metrics(read_log(storage, app_name, verstr))))
    return sides, None


def _metrics_delta(m1, m2):
    return {
        key: {"from": m1.get(key), "to": m2.get(key)}
        for key in sorted(set(m1) | set(m2))
        if m1.get(key) != m2.get(key)
    }


def _truncated(text):
    """``(text, truncated)`` with *text* cut at a line to fit the cap."""
    data = text.encode("utf-8")
    if len(data) <= MAX_DIFF_BYTES:
        return text, False
    cut = data.rfind(b"\n", 0, MAX_DIFF_BYTES) + 1
    return data[:cut].decode("utf-8", "ignore"), True


def _tree_diff(root_path, app_name, v1, side1, v2, side2):
    """``(fields, err)`` — the ``diff`` text (capped), or why there is none."""
    for verstr, (meta, _, _) in ((v1, side1), (v2, side2)):
        if not meta.get("base_commit"):
            return {"diff": None, "truncated": False,
                    "diff_unavailable": NO_BASE_COMMIT.format(verstr)}, None
    # Materialization only needs a root path (both sides have base_commit).
    vcs_stub = SimpleNamespace(vmn_root_path=root_path, name=app_name)
    text, err = render_tree_diff(vcs_stub, v1, side1[0], side1[1], v2, side2[0], side2[1])
    if err:
        return None, err
    text, truncated = _truncated(text)
    return {"diff": text, "truncated": truncated}, None


def experiment_diff(root_path, app_name, ref1, ref2):
    """Compare two experiments. Returns (result, error_message_or_None)."""
    storage = experiment_storage(root_path)
    verstrs, err = _resolve_pair(storage, app_name, ref1, ref2)
    if err:
        return None, err
    sides, err = _load_sides(storage, app_name, verstrs, load_log)
    if err:
        return None, err
    (v1, v2), (side1, side2) = verstrs, sides
    tree, err = _tree_diff(root_path, app_name, v1, side1, v2, side2)
    if err:
        return None, err
    result = {"from_verstr": v1, "to_verstr": v2, "metrics_delta": _metrics_delta(side1[2], side2[2])}
    result.update(tree)
    return result, None


def cached_experiment_diff(root_path, app_name, ref1, ref2):
    """:func:`experiment_diff` through :data:`DIFF_CACHE` (may raise DiffBusy)."""
    storage = experiment_storage(root_path)
    verstrs, err = _resolve_pair(storage, app_name, ref1, ref2)
    if err:
        return None, err
    key = (root_path, app_name) + tuple(_record_key(storage, app_name, v) for v in verstrs)
    return DIFF_CACHE.run(key, lambda: experiment_diff(root_path, app_name, *verstrs))


def _merged_log(storage, app_name, verstr):
    if hasattr(storage, "load_merged_log"):
        return storage.load_merged_log(app_name, verstr)
    return load_log(storage, app_name, verstr)


def experiment_diff_from_storage(storage, app_name, ref1, ref2):
    """Compare two experiments from a storage backend (S3). Metrics-only
    comparison: tree diffs are unavailable without a local checkout."""
    verstrs, err = _resolve_pair(storage, app_name, ref1, ref2)
    if err:
        return None, err
    sides, err = _load_sides(storage, app_name, verstrs, _merged_log)
    if err:
        return None, err
    return {
        "from_verstr": verstrs[0],
        "to_verstr": verstrs[1],
        "metrics_delta": _metrics_delta(sides[0][2], sides[1][2]),
        "diff": None,  # Tree diffs unavailable for S3 workspaces
        "truncated": False,
    }, None
