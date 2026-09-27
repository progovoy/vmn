"""Pure-function tests for experiment_inputs.py — entry shapes, validation, defaults."""
import pytest

from version_stamp.core.experiment_inputs import (
    create_input_entry,
    default_input_name,
    fold_inputs,
    valid_input_entry,
)


def test_create_input_entry_minimal():
    e = create_input_entry("s3://bucket/data.csv")
    assert e["type"] == "input"
    assert e["uri"] == "s3://bucket/data.csv"
    assert "name" in e
    assert e["digest"] is None
    assert e["kind"] is None


def test_create_input_entry_all_fields():
    e = create_input_entry(
        "s3://bucket/data.csv",
        name="train",
        digest="sha256:abc",
        kind="dataset",
        ts="2026-01-01T00:00:00Z",
    )
    assert e["type"] == "input"
    assert e["name"] == "train"
    assert e["uri"] == "s3://bucket/data.csv"
    assert e["digest"] == "sha256:abc"
    assert e["kind"] == "dataset"
    assert e["ts"] == "2026-01-01T00:00:00Z"


def test_create_input_entry_defaults_name_from_uri():
    e = create_input_entry("s3://bucket/train.csv")
    assert e["name"] == "train"


def test_default_input_name_basename_strips_extension():
    assert default_input_name("s3://bucket/data.csv") == "data"


def test_default_input_name_no_extension():
    assert default_input_name("s3://bucket/dataset") == "dataset"


def test_default_input_name_sanitizes_special_chars():
    # Non-alphanumeric (except _ and -) replaced with _
    assert default_input_name("http://host/path/my data@2023.json") == "my_data_2023"


def test_default_input_name_trailing_slash():
    assert default_input_name("s3://bucket/train/") == "train"


def test_default_input_name_multiple_extensions():
    # Dots in the root are also sanitized to keep identifiers query-safe.
    assert default_input_name("s3://bucket/archive.tar.gz") == "archive_tar"


def test_valid_input_entry_ok():
    assert valid_input_entry(
        {"type": "input", "uri": "s3://x", "name": "x", "digest": None, "kind": None, "ts": None}
    )


def test_valid_input_entry_missing_uri_rejected():
    assert not valid_input_entry({"type": "input", "name": "x"})


def test_valid_input_entry_wrong_type_rejected():
    assert not valid_input_entry({"type": "metrics", "uri": "s3://x"})


def test_valid_input_entry_extra_fields_rejected():
    assert not valid_input_entry(
        {"type": "input", "uri": "s3://x", "name": "x", "digest": None, "kind": None, "ts": None, "extra": "bad"}
    )


def test_fold_inputs_basic():
    entries = [
        {
            "type": "input",
            "uri": "s3://a",
            "name": "train",
            "digest": "sha256:1",
            "kind": "dataset",
            "ts": "2026-01-01T00:00:00Z",
        },
    ]
    result = fold_inputs(entries)
    assert result == {"train": {"uri": "s3://a", "digest": "sha256:1", "kind": "dataset"}}


def test_fold_inputs_last_ts_wins():
    entries = [
        {"type": "input", "uri": "s3://old", "name": "train", "digest": None, "kind": None, "ts": "2026-01-01T00:00:00Z"},
        {"type": "input", "uri": "s3://new", "name": "train", "digest": None, "kind": None, "ts": "2026-01-02T00:00:00Z"},
    ]
    result = fold_inputs(entries)
    assert result["train"]["uri"] == "s3://new"


def test_fold_inputs_skips_non_input_entries():
    entries = [
        {"type": "metrics", "values": {"loss": 0.5}},
        {"type": "input", "uri": "s3://a", "name": "train", "digest": None, "kind": None, "ts": None},
    ]
    result = fold_inputs(entries)
    assert list(result.keys()) == ["train"]


def test_fold_inputs_multiple_names():
    entries = [
        {"type": "input", "uri": "s3://a", "name": "train", "digest": None, "kind": None, "ts": None},
        {"type": "input", "uri": "s3://b", "name": "val", "digest": None, "kind": None, "ts": None},
    ]
    result = fold_inputs(entries)
    assert set(result.keys()) == {"train", "val"}
