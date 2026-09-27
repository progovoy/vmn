"""Tests for inputs/env query extensions in experiment_query.py."""
import pytest

from version_stamp.core.experiment_query import QueryError, compile_query, filter_rows


def _row(**kw):
    base = {
        "idx": 1,
        "verstr": "0.0.1",
        "code_verstr": "0.0.1",
        "timestamp": "2026-01-01T00:00:00Z",
        "note": None,
        "branch": "main",
        "base_version": "0.0.1",
        "parent": None,
        "metrics": {},
        "params": {},
        "tags": {},
        "status": "succeeded",
        "tree_status": "succeeded",
        "kind": "single",
        "depth": 0,
        "exit_code": 0,
        "duration_sec": 10.0,
        "inputs": {},
        "env": None,
        "imported_from": None,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# inputs.name.field (3-part)
# ---------------------------------------------------------------------------


def test_inputs_uri_matches():
    row = _row(inputs={"train": {"uri": "s3://bucket/train.csv", "digest": None, "kind": "dataset"}})
    assert compile_query('inputs.train.uri = "s3://bucket/train.csv"')(row)


def test_inputs_uri_no_match():
    row = _row(inputs={"train": {"uri": "s3://other.csv", "digest": None, "kind": None}})
    assert not compile_query('inputs.train.uri = "s3://bucket/train.csv"')(row)


def test_inputs_digest_3part():
    row = _row(inputs={"train": {"uri": "s3://a", "digest": "sha256:abc", "kind": None}})
    assert compile_query('inputs.train.digest = "sha256:abc"')(row)


def test_inputs_kind_3part():
    row = _row(inputs={"train": {"uri": "s3://a", "digest": None, "kind": "dataset"}})
    assert compile_query('inputs.train.kind = "dataset"')(row)


def test_inputs_missing_name_is_false():
    row = _row(inputs={})
    assert not compile_query('inputs.missing.uri = "s3://a"')(row)


def test_inputs_missing_inputs_dict_is_false():
    row = _row()
    row["inputs"] = None
    assert not compile_query('inputs.something.uri = "s3://a"')(row)


# ---------------------------------------------------------------------------
# env.key (2-part) and env.packages.pkg (3-part)
# ---------------------------------------------------------------------------


def test_env_python_2part():
    row = _row(env={"python": "3.11.0", "packages": {}})
    assert compile_query('env.python = "3.11.0"')(row)


def test_env_packages_3part():
    row = _row(env={"python": "3.11.0", "packages": {"torch": "2.0.0"}})
    assert compile_query('env.packages.torch = "2.0.0"')(row)


def test_env_packages_missing_pkg_is_false():
    row = _row(env={"python": "3.11.0", "packages": {}})
    assert not compile_query('env.packages.numpy = "1.0.0"')(row)


def test_env_none_row_returns_null():
    row = _row(env=None)
    assert compile_query("env.python = null")(row)


def test_env_none_packages_returns_null():
    row = _row(env=None)
    assert compile_query("env.packages.torch = null")(row)


# ---------------------------------------------------------------------------
# imported_from (bare ROW_FIELD)
# ---------------------------------------------------------------------------


def test_imported_from_match():
    row = _row(imported_from="mlflow")
    assert compile_query('imported_from = "mlflow"')(row)


def test_imported_from_null_when_absent():
    row = _row(imported_from=None)
    assert compile_query("imported_from = null")(row)


def test_imported_from_not_match():
    row = _row(imported_from=None)
    assert not compile_query('imported_from = "mlflow"')(row)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_unknown_3part_path_raises_query_error():
    with pytest.raises(QueryError):
        compile_query('foo.bar.baz = "x"')


def test_inputs_bad_subfield_raises_query_error():
    with pytest.raises(QueryError):
        compile_query('inputs.train.badfield = "x"')


def test_env_non_packages_3part_raises_query_error():
    """env.notpackages.something is not a valid 3-part path."""
    with pytest.raises(QueryError):
        compile_query('env.notpackages.something = "x"')


def test_4part_path_raises_query_error():
    with pytest.raises(QueryError):
        compile_query('env.x.y.z = "a"')
