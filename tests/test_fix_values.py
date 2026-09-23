"""Metric value hygiene: what reaches the log, the fold and the sort.

One bad value used to poison a whole app: numpy/torch scalars were written as
strings (``json.dumps(default=str)``), string metrics broke sorting with a
TypeError, NaN params were folded into metrics, and rows *without* the sort
metric floated to the top of a descending leaderboard.
"""
import json
import logging
import math

import numpy as np
import pytest

from version_stamp.core.experiment_log import latest_metrics, sort_by_metric
from version_stamp.core.experiment_writer import append_to_log


class _Storage:
    def __init__(self):
        self.entries = []

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        # Round-trip through JSON the way the real storages do.
        self.entries.append(json.loads(json.dumps(entry, default=str)))


class _TensorLike:
    """Duck-types a 0-d torch tensor: no float subclass, but ``.item()``."""

    def __init__(self, value):
        self._value = value

    def item(self):
        return self._value

    def __repr__(self):
        return f"tensor({self._value})"


def _metrics(values):
    storage = _Storage()
    append_to_log(storage, "app", "v", {"type": "metrics", "values": values})
    return storage.entries


def _one(values):
    entries = _metrics(values)
    assert len(entries) == 1
    return entries[0]["values"]


# ---- write-side coercion ---------------------------------------------------


def test_numpy_scalars_are_recorded_as_numbers():
    values = _one({"f32": np.float32(0.5), "i64": np.int64(3), "f64": np.float64(1.5)})
    assert values == {"f32": 0.5, "i64": 3.0, "f64": 1.5}
    assert all(isinstance(v, float) for v in values.values())


def test_zero_d_array_is_recorded_as_a_number():
    assert _one({"x": np.array(0.25)}) == {"x": 0.25}


def test_tensor_like_scalar_is_recorded_via_item():
    assert _one({"loss": _TensorLike(0.125)}) == {"loss": 0.125}


def test_numeric_string_is_coerced():
    assert _one({"acc": "0.9"}) == {"acc": 0.9}


def test_plain_ints_and_floats_are_kept():
    assert _one({"a": 1, "b": 2.5}) == {"a": 1, "b": 2.5}


def test_non_finite_values_are_kept_because_they_are_truthful():
    values = _one({"loss": float("nan"), "grad": float("inf")})
    assert math.isnan(values["loss"])
    assert values["grad"] == float("inf")


def test_booleans_are_not_metrics():
    assert _one({"done": True, "acc": 0.5}) == {"acc": 0.5}


def test_non_numeric_values_are_dropped_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        values = _one({"tag": "éé", "acc": 0.5, "status": "n/a"})
    assert values == {"acc": 0.5}
    assert "tag" in caplog.text and "status" in caplog.text


def test_vectors_are_not_metrics():
    assert _one({"v": [1, 2], "a": np.array([1.0, 2.0]), "ok": 1.0}) == {"ok": 1.0}


def test_entry_with_nothing_numeric_is_skipped():
    assert _metrics({"tag": "x", "flag": False}) == []


def test_caller_entry_is_not_mutated():
    entry = {"type": "metrics", "values": {"x": np.float32(1.0), "t": "s"}}
    append_to_log(_Storage(), "app", "v", entry)
    assert set(entry["values"]) == {"x", "t"}


def test_params_entries_are_kept_verbatim_but_json_safe():
    storage = _Storage()
    append_to_log(
        storage,
        "app",
        "v",
        {"type": "params", "params": {"depth": np.int64(3), "opt": "adam", "on": True}},
    )
    params = storage.entries[0]["params"]
    assert params == {"depth": 3, "opt": "adam", "on": True}
    assert isinstance(params["depth"], int)


def test_create_entry_params_are_json_safe():
    storage = _Storage()
    append_to_log(
        storage, "app", "v", {"type": "create", "params": {"lr": np.float32(0.5)}}
    )
    assert storage.entries[0]["params"] == {"lr": 0.5}


def test_other_entry_types_pass_through():
    storage = _Storage()
    append_to_log(storage, "app", "v", {"type": "note", "text": "hi"})
    assert storage.entries == [{"type": "note", "text": "hi"}]


# ---- fold ------------------------------------------------------------------


def test_fold_skips_non_finite_params():
    log = [{"type": "create", "params": {"missing": float("nan"), "big": float("inf")}}]
    assert latest_metrics(log) == {}


def test_fold_keeps_boolean_params_as_numbers():
    # Documented behaviour pinned by test_ui_experiment_status: bools fold as 1.0/0.0.
    log = [{"type": "params", "params": {"verbose": True, "lr": 0.1}}]
    assert latest_metrics(log) == {"verbose": 1.0, "lr": 0.1}


def test_fold_still_folds_numeric_string_params():
    log = [{"type": "create", "params": {"lr": "0.01"}}]
    assert latest_metrics(log) == {"lr": 0.01}


def test_fold_skips_non_finite_string_params():
    log = [{"type": "create", "params": {"missing": "nan"}}]
    assert latest_metrics(log) == {}


# ---- sort ------------------------------------------------------------------


def _rows(*values):
    rows = []
    for i, v in enumerate(values):
        rows.append({"verstr": f"r{i}", "metrics": {} if v is ... else {"acc": v}})
    return rows


def _order(rows):
    return [r["verstr"] for r in rows]


MAX = {"acc": {"goal": "max", "primary": True}}
MIN = {"acc": {"goal": "min", "primary": True}}


def test_descending_sort_puts_missing_rows_last():
    rows = _rows(0.91, ..., 0.95, ...)
    assert _order(sort_by_metric(rows, MAX)) == ["r2", "r0", "r1", "r3"]


def test_ascending_sort_puts_missing_rows_last():
    rows = _rows(..., 0.3, 0.1)
    assert _order(sort_by_metric(rows, MIN)) == ["r2", "r1", "r0"]


@pytest.mark.parametrize("schema", [MAX, MIN])
def test_nan_none_and_strings_sort_last_and_stable(schema):
    rows = _rows(float("nan"), 0.5, None, "n/a", 0.1, float("inf"))
    ordered = _order(sort_by_metric(rows, schema))
    assert ordered[-4:] == ["r0", "r2", "r3", "r5"]
    expected = ["r1", "r4"] if schema is MAX else ["r4", "r1"]
    assert ordered[:2] == expected


def test_sort_with_nan_is_total_and_does_not_raise():
    rows = _rows(0.5, float("nan"), 0.1, 0.9, "x")
    ordered = _order(sort_by_metric(rows, MIN))
    assert ordered == ["r2", "r0", "r3", "r1", "r4"]


def test_explicit_sort_key_absent_from_schema_is_ascending_with_missing_last():
    rows = [
        {"verstr": "a", "metrics": {}},
        {"verstr": "b", "metrics": {"loss": 0.9}},
        {"verstr": "c", "metrics": {"loss": 0.1}},
    ]
    assert _order(sort_by_metric(rows, {}, sort="loss")) == ["c", "b", "a"]
