"""`get_run` resolves and places a run through the experiment index: it reads
the one run, never every record's metadata."""
import os

import pytest
import yaml
from helpers import _storage

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core import experiment_index
from version_stamp.exp.reader import get_run


def _write(app_layout, verstr, second, parent=None):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path)
    meta = {"verstr": verstr, "code_verstr": verstr, "note": f"n-{verstr}",
            "timestamp": f"2026-09-21T12:00:{second:02d}Z"}
    if parent:
        meta["parent"] = parent
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)


OUTER, INNER, LONE = "0.0.1-dev.aaaa111", "0.0.1-dev.bbbb222", "0.0.2-dev.cccc333"


@pytest.fixture
def seeded(app_layout):
    _write(app_layout, OUTER, 1)
    _write(app_layout, INNER, 2, parent=OUTER)
    _write(app_layout, LONE, 3)
    return app_layout


def _refuse_full_listing(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("get_run read every record's metadata")

    monkeypatch.setattr(LocalSnapshotStorage, "list_snapshots", refuse)


@pytest.mark.parametrize(
    "ref,verstr,idx",
    [("@1", OUTER, 1), (OUTER, OUTER, 1), ("0.0.1-dev.b", INNER, 2), ("latest", LONE, 3)],
)
def test_get_run_reads_no_full_listing(seeded, monkeypatch, ref, verstr, idx):
    _refuse_full_listing(monkeypatch)
    run = get_run(seeded.app_name, ref, storage=_storage(seeded))
    assert (run["verstr"], run["idx"]) == (verstr, idx)
    assert run["note"] == f"n-{verstr}"
    if verstr == OUTER:
        assert run["children"] == [INNER] and run["kind"] == "outer"


def test_get_run_matches_the_direct_path_when_the_index_fails(seeded, monkeypatch):
    indexed = get_run(seeded.app_name, OUTER, storage=_storage(seeded))

    def broken(*a, **kw):
        raise RuntimeError("no index today")

    monkeypatch.setattr(experiment_index, "shared_index", broken)
    direct = get_run(seeded.app_name, OUTER, storage=_storage(seeded))
    for key in ("heartbeat", "duration_sec"):
        indexed.pop(key, None), direct.pop(key, None)
    assert indexed == direct


def test_get_run_of_an_unknown_stamped_version_raises(seeded, monkeypatch):
    _refuse_full_listing(monkeypatch)
    with pytest.raises(ValueError, match="not found"):
        get_run(seeded.app_name, "9.9.9", storage=_storage(seeded))
