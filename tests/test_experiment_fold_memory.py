"""A fold's per-field bookkeeping (value + provenance) must stay compact.

Every folded field carries a small wrapper — the value and the ``(timestamp,
writer, position)`` that won it — alongside the value itself. Nested Python
lists cost far more than their logical payload (list object header + a
separately allocated item array, twice over for the nested provenance key),
so a run with a modest number of metrics/params multiplies that overhead
across every field, and every run in the experiment index.

This measures the actual retained memory of a realistic fold (20 metrics +
10 params, as in the regression this guards) via a recursive ``sys.getsizeof``
walk, and pins a ceiling well below the pre-fix, list-of-list cost.
"""
import sys

from version_stamp.core.experiment_fold import apply_entries, fold_values, new_fold

N_METRICS = 20
N_PARAMS = 10

# Pre-fix (nested lists: [value, [ts, writer, pos]]) measures ~11.6KB for this
# fixture — two list allocations per field, each paying full list overhead
# (and unable to share a per-entry key across the params/metrics-folded-in
# pair once flattened). The fix (one flat tuple per field) measures ~9.9KB.
MAX_BYTES = 10500


def _deep_sizeof(obj, seen=None):
    seen = seen if seen is not None else set()
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for key, value in obj.items():
            size += _deep_sizeof(key, seen)
            size += _deep_sizeof(value, seen)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            size += _deep_sizeof(item, seen)
    return size


def _realistic_fold():
    """A single run's fold: 20 logged metrics plus 10 create-time params,
    the shape the experiment index folds per record via ``apply_entries``."""
    fold = new_fold()
    entries = [
        {
            "timestamp": f"2026-01-01T00:00:{i:02d}Z",
            "type": "metrics",
            "values": {f"metric_{i}": float(i)},
        }
        for i in range(N_METRICS)
    ]
    entries.append(
        {
            "timestamp": "2026-01-01T00:01:00Z",
            "type": "create",
            "params": {f"param_{i}": float(i) for i in range(N_PARAMS)},
        }
    )
    apply_entries(fold, "writer0", 0, entries)
    return fold


def test_fold_field_storage_stays_under_a_memory_ceiling():
    fold = _realistic_fold()
    assert len(fold["metrics"]) == N_METRICS + N_PARAMS
    assert len(fold["params"]) == N_PARAMS

    size = _deep_sizeof(fold["metrics"]) + _deep_sizeof(fold["params"])
    assert size < MAX_BYTES, f"folded metrics+params retained {size} bytes"


def test_the_flattened_wrapper_still_lets_the_latest_key_win():
    """A field's stored wrapper is one flat tuple, not a value/key pair — but
    the "latest write wins" comparison must still see the full provenance
    (timestamp, writer, position), not just the value. A later position from
    the same writer overrides an earlier one from that writer; an earlier
    timestamp from another writer does not override either."""
    fold = new_fold()
    apply_entries(fold, "a", 0, [
        {"timestamp": "t1", "type": "metrics", "values": {"loss": 1.0}},
    ])
    apply_entries(fold, "a", 1, [
        {"timestamp": "t1", "type": "metrics", "values": {"loss": 2.0}},
    ])
    apply_entries(fold, "b", 0, [
        {"timestamp": "t0", "type": "metrics", "values": {"loss": 3.0}},
    ])
    assert fold_values(fold, "metrics")["loss"] == 2.0
