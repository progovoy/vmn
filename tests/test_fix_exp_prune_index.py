"""Prune selects through the experiment index: no per-record metadata or run
state reads, same choice as the direct path."""
from types import SimpleNamespace

import pytest
import yaml

from version_stamp.cli import experiment_prune as prune_mod
from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage
from version_stamp.core.logging import init_stamp_logger

APP = "app"


@pytest.fixture(autouse=True)
def _logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


def _meta(verstr, second, parent=None):
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{second:02d}Z"}
    if parent:
        meta["parent"] = parent
    return meta


def _finished():
    return {"state": "finished", "exit_code": 0, "heartbeat": "2026-01-01T00:00:00Z",
            "heartbeat_interval_sec": 30}


@pytest.fixture
def st(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "experiments"))
    for i in range(6):
        verstr = f"0.0.1-dev.h.r{i}"
        parent = "0.0.1-dev.h.r0" if i == 5 else None
        storage.save(APP, verstr, _meta(verstr, i, parent), {})
        storage.save_file(APP, verstr, "run_state.yml", yaml.dump(_finished()))
    return storage


def _args(**kw):
    return SimpleNamespace(**dict(dict(keep=2, older_than=None, force=False,
                                       dry_run=True), **kw))


def test_prune_selects_through_the_index(st, monkeypatch, capfd):
    calls = []
    monkeypatch.setattr(st, "list_snapshots",
                        lambda app: calls.append("list_snapshots") or [])
    monkeypatch.setattr(prune_mod, "load_run_state",
                        lambda *a: calls.append("load_run_state"))
    assert prune_mod.experiment_prune(None, {}, st, _args(), APP) == 0
    assert calls == []
    out = capfd.readouterr().out
    # r0 has a kept child (r5), so only r1..r3 go.
    assert "Would delete 3 experiments" in out
    for i in (1, 2, 3):
        assert f"0.0.1-dev.h.r{i}" in out
    assert "0.0.1-dev.h.r0\n" not in out
