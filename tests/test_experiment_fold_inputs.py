"""Tests for input-entry folding in experiment_fold.py and fold_row provenance fields."""
import pytest

from version_stamp.core.experiment_fold import (
    apply_entries,
    fold_log,
    fold_row,
    new_fold,
)


def _input_entry(uri, name, ts, digest=None, kind=None):
    return {
        "type": "input",
        "uri": uri,
        "name": name,
        "digest": digest,
        "kind": kind,
        "timestamp": ts,
    }


# ---------------------------------------------------------------------------
# Folding mechanics
# ---------------------------------------------------------------------------


def test_input_entry_folds_into_fold():
    fold = new_fold()
    apply_entries(fold, "w1", 0, [_input_entry("s3://a", "train", "2026-01-01T00:00:00Z")])
    assert "train" in fold.get("inputs", {})


def test_last_write_wins_across_writers():
    """A later-ts write (even from another writer) wins over an earlier one."""
    fold = new_fold()
    apply_entries(fold, "w1", 0, [_input_entry("s3://old", "train", "2026-01-01T00:00:00Z")])
    apply_entries(fold, "w2", 0, [_input_entry("s3://new", "train", "2026-01-02T00:00:00Z")])
    assert fold["inputs"]["train"][0]["uri"] == "s3://new"


def test_earlier_write_does_not_overwrite_later():
    """Applying an older entry after a newer one must not displace the newer."""
    fold = new_fold()
    apply_entries(fold, "w2", 0, [_input_entry("s3://new", "train", "2026-01-02T00:00:00Z")])
    apply_entries(fold, "w1", 0, [_input_entry("s3://old", "train", "2026-01-01T00:00:00Z")])
    assert fold["inputs"]["train"][0]["uri"] == "s3://new"


def test_inputs_stored_with_uri_digest_kind():
    fold = new_fold()
    apply_entries(
        fold, "w1", 0,
        [_input_entry("s3://a", "train", "2026-01-01T00:00:00Z", digest="sha256:1", kind="dataset")],
    )
    stored = fold["inputs"]["train"][0]
    assert stored == {"uri": "s3://a", "digest": "sha256:1", "kind": "dataset"}


# ---------------------------------------------------------------------------
# Backward compat: persisted folds without "inputs" key
# ---------------------------------------------------------------------------


def test_persisted_fold_without_inputs_key_produces_valid_row():
    """A fold persisted before this feature (no 'inputs' key) loads without error."""
    old_fold = new_fold()
    assert "inputs" not in old_fold  # sanity: new_fold() does not add it
    meta = {"verstr": "0.0.1", "timestamp": "2026-01-01T00:00:00Z"}
    row = fold_row(1, meta, old_fold)
    assert row["inputs"] == {}


# ---------------------------------------------------------------------------
# fold_row provenance fields
# ---------------------------------------------------------------------------


def test_row_carries_env_from_meta():
    fold = new_fold()
    meta = {"verstr": "0.0.1", "env": {"python": "3.11.0", "packages": {"torch": "2.0.0"}}}
    row = fold_row(1, meta, fold)
    assert row["env"]["python"] == "3.11.0"
    assert row["env"]["packages"]["torch"] == "2.0.0"


def test_row_env_absent_when_not_in_meta():
    fold = new_fold()
    meta = {"verstr": "0.0.1"}
    row = fold_row(1, meta, fold)
    assert "env" not in row or row.get("env") is None


def test_row_carries_imported_from():
    fold = new_fold()
    meta = {"verstr": "0.0.1", "imported_from": "mlflow"}
    row = fold_row(1, meta, fold)
    assert row["imported_from"] == "mlflow"


def test_row_imported_from_absent_by_default():
    fold = new_fold()
    meta = {"verstr": "0.0.1"}
    row = fold_row(1, meta, fold)
    assert row.get("imported_from") is None


# ---------------------------------------------------------------------------
# fold_log exposes inputs
# ---------------------------------------------------------------------------


def test_fold_log_exposes_inputs():
    log = [
        {"type": "create", "params": {}},
        _input_entry("s3://a", "train", "2026-01-01T00:00:00Z", digest="sha256:abc", kind="dataset"),
    ]
    fold = fold_log(log)
    assert "train" in fold.get("inputs", {})
    assert fold["inputs"]["train"][0]["uri"] == "s3://a"


def test_fold_log_inputs_last_entry_wins():
    log = [
        _input_entry("s3://old", "train", "2026-01-01T00:00:00Z"),
        _input_entry("s3://new", "train", "2026-01-02T00:00:00Z"),
    ]
    fold = fold_log(log)
    assert fold["inputs"]["train"][0]["uri"] == "s3://new"
