"""Prune guards at scale: a stuck run may be alive, deletes run concurrently
against a remote, and a failed listing deletes nothing."""
import datetime
import threading
from types import SimpleNamespace

import pytest
import yaml

from version_stamp.cli.experiment_prune import experiment_prune
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


def _ago(minutes):
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=minutes
    )
    return ts.isoformat()


def _state(heartbeat_minutes_ago):
    return {
        "state": "running",
        "heartbeat": _ago(heartbeat_minutes_ago),
        "heartbeat_interval_sec": 30,
        "exit_code": None,
    }


class _Storage:
    def __init__(self, states, remote=False):
        self.states = states
        self.deleted = []
        self.remote = remote
        self.threads = set()
        self._lock = threading.Lock()

    def list_snapshots(self, app_name):
        return [
            {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}
            for i, v in enumerate(self.states)
        ]

    def load_file(self, app_name, verstr, name):
        state = self.states[verstr]
        return yaml.dump(state).encode() if state else None

    def delete(self, app_name, verstr):
        with self._lock:
            self.deleted.append(verstr)
            self.threads.add(threading.get_ident())

    def is_remote(self):
        return self.remote


def _args(**kw):
    return SimpleNamespace(**dict(dict(keep=0, older_than=None, force=False), **kw))


def test_prune_skips_stuck_runs(capfd):
    storage = _Storage({"stuck": _state(10), "done": None})
    assert experiment_prune(None, {}, storage, _args(), "app") == 0
    assert storage.deleted == ["done"]
    out = capfd.readouterr().out
    assert "Skipping stuck" in out and "--force" in out


def test_prune_force_deletes_stuck_runs():
    storage = _Storage({"stuck": _state(10)})
    assert experiment_prune(None, {}, storage, _args(force=True), "app") == 0
    assert storage.deleted == ["stuck"]


def test_prune_deletes_remote_runs_concurrently(capfd):
    storage = _Storage({f"v{i}": None for i in range(8)}, remote=True)
    barrier = threading.Barrier(2, timeout=5)
    real = storage.delete

    def delete(app_name, verstr):
        if verstr in ("v0", "v1"):
            barrier.wait()
        real(app_name, verstr)

    storage.delete = delete
    assert experiment_prune(None, {}, storage, _args(), "app") == 0
    assert sorted(storage.deleted) == [f"v{i}" for i in range(8)]
    out = capfd.readouterr().out
    assert out.index("Deleted v0") < out.index("Deleted v7")


def test_a_failed_listing_deletes_nothing():
    storage = _Storage({"v": None})

    def fail(app_name):
        raise ConnectionError("remote down")

    storage.list_snapshots = fail
    with pytest.raises(ConnectionError):
        experiment_prune(None, {}, storage, _args(), "app")
    assert storage.deleted == []
