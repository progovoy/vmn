"""A3: SDK ``Run.log_input`` and CLI ``--input`` flag.

Tests cover:
- parse_input_arg: pure-function, no Docker required.
- SDK log_input: appends an input entry into the log (needs app_layout).
- SDK NoOpRun.log_input: does nothing.
- CLI add/create/run accept --input (needs app_layout).
"""
import os
import sys

import pytest


# ---------------------------------------------------------------------------
# parse_input_arg — pure function, no Docker needed
# ---------------------------------------------------------------------------

def _parse(s):
    from version_stamp.cli.experiment_inputs_arg import parse_input_arg
    return parse_input_arg(s)


def test_parse_plain_uri():
    name, uri, digest = _parse("s3://bucket/data.csv")
    assert name is None
    assert uri == "s3://bucket/data.csv"
    assert digest is None


def test_parse_digest_via_hash():
    name, uri, digest = _parse("s3://bucket/data.csv#sha256:abc123")
    assert name is None
    assert uri == "s3://bucket/data.csv"
    assert digest == "sha256:abc123"


def test_parse_named_input():
    name, uri, digest = _parse("train=s3://bucket/train.csv")
    assert name == "train"
    assert uri == "s3://bucket/train.csv"
    assert digest is None


def test_parse_named_with_digest():
    name, uri, digest = _parse("train=s3://bucket/train.csv#sha256:deadbeef")
    assert name == "train"
    assert uri == "s3://bucket/train.csv"
    assert digest == "sha256:deadbeef"


def test_parse_uri_with_equals_no_name():
    """An = inside a URL query string (scheme :// precedes =) is not a name."""
    name, uri, digest = _parse("http://host/path?key=value")
    assert name is None
    assert uri == "http://host/path?key=value"
    assert digest is None


def test_parse_uri_with_equals_no_name_s3():
    """s3:// precedes = → no name extraction."""
    name, uri, digest = _parse("s3://bucket/path?foo=bar#digest")
    assert name is None
    assert uri == "s3://bucket/path?foo=bar"
    assert digest == "digest"


def test_parse_empty_digest_treated_as_none():
    """A trailing # with nothing after it yields digest=None."""
    name, uri, digest = _parse("s3://bucket/data#")
    assert uri == "s3://bucket/data"
    assert digest is None


def test_parse_last_hash_splits_digest():
    """When multiple # appear, only the last one splits the digest."""
    name, uri, digest = _parse("s3://bucket/data#part1#sha256:abc")
    assert uri == "s3://bucket/data#part1"
    assert digest == "sha256:abc"


def test_parse_non_identifier_before_equals_no_name():
    """A token like '123abc' before = is not a valid identifier → no name."""
    name, uri, digest = _parse("123abc=s3://bucket/data")
    assert name is None


# ---------------------------------------------------------------------------
# SDK: log_input appends an input entry
# ---------------------------------------------------------------------------

from helpers import _bootstrap, _storage  # noqa: E402


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def test_log_input_appends_input_entry(app_layout):
    _bootstrap(app_layout)
    from version_stamp.exp import start_run

    with start_run(app_layout.app_name) as run:
        run.log_input("s3://bucket/data.csv")
        verstr = run.id

    entries = [e for e in _log(app_layout, verstr) if e.get("type") == "input"]
    assert len(entries) == 1
    assert entries[0]["uri"] == "s3://bucket/data.csv"
    assert entries[0]["name"] == "data"  # default_input_name


def test_log_input_with_name_digest_kind(app_layout):
    _bootstrap(app_layout)
    from version_stamp.exp import start_run

    with start_run(app_layout.app_name) as run:
        run.log_input("s3://bucket/train.csv", name="train", digest="sha256:abc", kind="dataset")
        verstr = run.id

    entries = [e for e in _log(app_layout, verstr) if e.get("type") == "input"]
    assert len(entries) == 1
    e = entries[0]
    assert e["name"] == "train"
    assert e["uri"] == "s3://bucket/train.csv"
    assert e["digest"] == "sha256:abc"
    assert e["kind"] == "dataset"


def test_log_input_repeatable(app_layout):
    _bootstrap(app_layout)
    from version_stamp.exp import start_run

    with start_run(app_layout.app_name) as run:
        run.log_input("s3://bucket/a.csv", name="a")
        run.log_input("s3://bucket/b.csv", name="b")
        verstr = run.id

    entries = [e for e in _log(app_layout, verstr) if e.get("type") == "input"]
    assert len(entries) == 2
    names = {e["name"] for e in entries}
    assert names == {"a", "b"}


def test_noop_run_log_input_does_nothing():
    from version_stamp.exp.ranks import NoOpRun

    run = NoOpRun("test_app")
    # Should not raise and should return None
    result = run.log_input("s3://bucket/data")
    assert result is None


# ---------------------------------------------------------------------------
# CLI: --input on vmn exp create/add
# ---------------------------------------------------------------------------

from helpers import _experiment  # noqa: E402


def test_exp_create_with_input(app_layout):
    _bootstrap(app_layout)

    ret = _experiment(
        app_layout.app_name,
        action="create",
        extra_args=["--input", "s3://bucket/data.csv"],
    )
    assert ret == 0

    storage = _storage(app_layout)
    rows = storage.list_snapshots(app_layout.app_name)
    assert rows, "no runs created"
    verstr = rows[-1]["verstr"]
    entries = [e for e in storage.load_merged_log(app_layout.app_name, verstr)
               if e.get("type") == "input"]
    assert len(entries) == 1
    assert entries[0]["uri"] == "s3://bucket/data.csv"


def test_exp_create_with_named_input(app_layout):
    _bootstrap(app_layout)

    ret = _experiment(
        app_layout.app_name,
        action="create",
        extra_args=["--input", "train=s3://bucket/train.csv#sha256:abc"],
    )
    assert ret == 0

    storage = _storage(app_layout)
    rows = storage.list_snapshots(app_layout.app_name)
    verstr = rows[-1]["verstr"]
    entries = [e for e in storage.load_merged_log(app_layout.app_name, verstr)
               if e.get("type") == "input"]
    assert len(entries) == 1
    e = entries[0]
    assert e["name"] == "train"
    assert e["uri"] == "s3://bucket/train.csv"
    assert e["digest"] == "sha256:abc"


def test_exp_create_with_multiple_inputs(app_layout):
    _bootstrap(app_layout)

    ret = _experiment(
        app_layout.app_name,
        action="create",
        extra_args=[
            "--input", "s3://bucket/a.csv",
            "--input", "s3://bucket/b.csv",
        ],
    )
    assert ret == 0

    storage = _storage(app_layout)
    rows = storage.list_snapshots(app_layout.app_name)
    verstr = rows[-1]["verstr"]
    entries = [e for e in storage.load_merged_log(app_layout.app_name, verstr)
               if e.get("type") == "input"]
    assert len(entries) == 2


def test_exp_add_with_input(app_layout):
    _bootstrap(app_layout)

    # create first, then add input
    ret = _experiment(app_layout.app_name, action="create")
    assert ret == 0

    storage = _storage(app_layout)
    rows = storage.list_snapshots(app_layout.app_name)
    verstr = rows[-1]["verstr"]

    ret = _experiment(
        app_layout.app_name,
        action="add",
        version=verstr,
        extra_args=["--input", "s3://bucket/data.csv"],
    )
    assert ret == 0

    entries = [e for e in storage.load_merged_log(app_layout.app_name, verstr)
               if e.get("type") == "input"]
    assert len(entries) == 1
    assert entries[0]["uri"] == "s3://bucket/data.csv"


def test_exp_run_with_input(app_layout):
    _bootstrap(app_layout)

    ret = _experiment(
        app_layout.app_name,
        action="run",
        extra_args=["--input", "s3://bucket/data.csv"],
        run_cmd=[sys.executable, "-c", "pass"],
    )
    assert ret == 0

    storage = _storage(app_layout)
    rows = storage.list_snapshots(app_layout.app_name)
    verstr = rows[-1]["verstr"]
    entries = [e for e in storage.load_merged_log(app_layout.app_name, verstr)
               if e.get("type") == "input"]
    assert len(entries) == 1
    assert entries[0]["uri"] == "s3://bucket/data.csv"
