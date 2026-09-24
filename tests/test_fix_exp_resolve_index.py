"""Experiment references (``latest``, ``@N``, prefixes) resolve through the
experiment index, with exactly the results and errors of the storage walk."""
import os

import pytest
import yaml
from helpers import _storage

from version_stamp.cli.snapshot import LocalSnapshotStorage, _resolve_verstr
from version_stamp.core import experiment_index
from version_stamp.core.experiment_refs import resolve_experiment

APP_RUNS = [
    ("0.0.1-dev.aaaa111.bbbb222", "2026-09-21T12:00:01Z"),
    ("0.0.1-dev.aaaa111.bbbb222.r2", "2026-09-21T12:00:02Z"),
    ("0.0.1-dev.cccc333.dddd444", "2026-09-21T12:00:03Z"),
    ("0.0.2-dev.eeee555.ffff666", "2026-09-21T12:00:04Z"),
]

REFS = [
    (None, False),
    (None, True),
    ("latest", False),
    ("@latest", False),
    ("@1", False),
    ("@4", False),
    ("@0", False),
    ("@5", False),
    ("@x", False),
    ("@-1", False),
    ("0.0.1-dev.aaaa111.bbbb222", False),
    ("0.0.1-dev.aaaa", False),
    ("0.0.1-dev.cccc", False),
    ("0.0.2-dev.e", False),
    ("0.0.9-dev.nope", False),
    ("1.2.3", False),
]


def _write(app_layout, verstr, timestamp):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    meta = {"verstr": verstr, "code_verstr": verstr, "timestamp": timestamp}
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)


def _seed(app_layout):
    for verstr, ts in APP_RUNS:
        _write(app_layout, verstr, ts)


@pytest.fixture
def no_full_listing(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("resolution walked every record's metadata")

    monkeypatch.setattr(LocalSnapshotStorage, "list_snapshots", refuse)


@pytest.mark.parametrize("ref,latest", REFS)
def test_index_resolution_matches_the_storage_walk(app_layout, ref, latest):
    _seed(app_layout)
    storage = _storage(app_layout)
    expected = _resolve_verstr(
        storage, app_layout.app_name, ref, latest=latest, kind="experiment"
    )
    assert resolve_experiment(storage, app_layout.app_name, ref, latest=latest) == expected


@pytest.mark.parametrize("ref,latest", [("latest", False), ("@1", False)])
def test_resolution_matches_on_an_empty_app(app_layout, ref, latest):
    storage = _storage(app_layout)
    expected = _resolve_verstr(
        storage, app_layout.app_name, ref, latest=latest, kind="experiment"
    )
    assert expected[1]
    assert resolve_experiment(storage, app_layout.app_name, ref, latest=latest) == expected


@pytest.mark.parametrize("ref", ["latest", "@2", "0.0.1-dev.cccc", "0.0.1-dev.aaaa"])
def test_listing_refs_do_not_read_every_record(app_layout, no_full_listing, ref):
    _seed(app_layout)
    verstr, err = resolve_experiment(_storage(app_layout), app_layout.app_name, ref)
    assert verstr or err


@pytest.mark.parametrize("ref,latest", REFS)
def test_falls_back_to_the_storage_walk_when_the_index_fails(
    app_layout, monkeypatch, ref, latest
):
    _seed(app_layout)
    storage = _storage(app_layout)
    expected = _resolve_verstr(
        storage, app_layout.app_name, ref, latest=latest, kind="experiment"
    )

    def broken(*a, **kw):
        raise RuntimeError("no index today")

    monkeypatch.setattr(experiment_index, "shared_index", broken)
    assert resolve_experiment(storage, app_layout.app_name, ref, latest=latest) == expected


def test_a_run_created_after_the_index_loaded_resolves(app_layout):
    _seed(app_layout)
    storage = _storage(app_layout)
    assert resolve_experiment(storage, app_layout.app_name, "@4")[0] == APP_RUNS[3][0]
    _write(app_layout, "0.0.3-dev.1111111.2222222", "2026-09-21T12:00:05Z")
    assert resolve_experiment(storage, app_layout.app_name, "latest") == (
        "0.0.3-dev.1111111.2222222",
        None,
    )
