"""Stuck needs BOTH clocks stale: the writer's heartbeat timestamp and the
store's write time of run_state.yml. A fresh store write proves a run alive
even when its writer's clock lags; without a store time the heartbeat decides.
Covers the core rule, the SDK reader, ``vmn exp list``/``show`` and prune."""
import datetime
import os
import time
from types import SimpleNamespace

import pytest
import yaml
from helpers import _bootstrap, _exp, _storage

from version_stamp.cli.experiment_prune import experiment_prune
from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage
from version_stamp.core import experiment_status as st
from version_stamp.core.logging import init_stamp_logger

NOW = datetime.datetime(2026, 9, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _ago(seconds, now=None):
    return (now or datetime.datetime.now(datetime.timezone.utc)) - datetime.timedelta(
        seconds=seconds
    )


def _running(heartbeat_ago, now=None):
    return {
        "state": "running",
        "started_at": _iso(_ago(7200, now)),
        "heartbeat": _iso(_ago(heartbeat_ago, now)),
        "heartbeat_interval_sec": 30,
        "exit_code": None,
    }


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------


def test_fresh_heartbeat_keeps_a_run_alive_despite_a_stale_store_write():
    state = _running(heartbeat_ago=5, now=NOW)
    assert st.derive_status(state, now=NOW, observed_at=_ago(600, NOW)) == st.RUNNING


def test_both_clocks_stale_is_stuck():
    state = _running(heartbeat_ago=600, now=NOW)
    assert st.derive_status(state, now=NOW, observed_at=_ago(600, NOW)) == st.STUCK


def test_unknown_store_time_falls_back_to_the_heartbeat():
    assert st.derive_status(_running(600, NOW), now=NOW, observed_at=None) == st.STUCK
    assert st.derive_status(_running(5, NOW), now=NOW, observed_at=None) == st.RUNNING


def test_stale_sec_is_the_age_of_the_freshest_proof_of_life():
    fields = st.status_fields(_running(20, NOW), now=NOW, observed_at=_ago(600, NOW))
    assert fields["stale_sec"] == 20.0


# ---------------------------------------------------------------------------
# on-disk fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


def _write_run(app_layout, verstr, run_state, store_age_sec=None):
    """An experiment dir with a stale-heartbeat run state; *store_age_sec*
    ages the file's mtime (None: just written)."""
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    meta = {"verstr": verstr, "code_verstr": verstr, "branch": "master",
            "timestamp": "2026-09-21T12:00:01", "base_version": "0.0.1"}
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    state_path = os.path.join(path, "run_state.yml")
    with open(state_path, "w") as f:
        yaml.dump(run_state, f)
    if store_age_sec is not None:
        aged = time.time() - store_age_sec
        os.utime(state_path, (aged, aged))
    return path


@pytest.fixture
def no_store_mtime(monkeypatch):
    """A backend whose listing carries no mtime (observed_at unknown)."""
    real = LocalSnapshotStorage._files_in

    def files_in(path):
        return {name: (sig[0], None) for name, sig in real(path).items()}

    monkeypatch.setattr(LocalSnapshotStorage, "_files_in", staticmethod(files_in))


# ---------------------------------------------------------------------------
# SDK reader
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_index", [True, False])
def test_sdk_rows_trust_a_fresh_store_write(app_layout, use_index):
    from version_stamp.exp.reader import list_runs

    _write_run(app_layout, "0.0.1", _running(600))
    _write_run(app_layout, "0.0.2", _running(600), store_age_sec=900)

    rows = list_runs(app_layout.app_name, storage=_storage(app_layout),
                     use_index=use_index)
    assert {r["verstr"]: r["status"] for r in rows} == {
        "0.0.1": "running", "0.0.2": "stuck",
    }


def test_sdk_rows_without_a_store_time_use_the_heartbeat(app_layout, no_store_mtime):
    from version_stamp.exp.reader import list_runs

    _write_run(app_layout, "0.0.1", _running(600))
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout))
    assert rows[0]["status"] == "stuck"


def test_sdk_get_run_trusts_a_fresh_store_write(app_layout):
    from version_stamp.exp.reader import get_run

    _write_run(app_layout, "0.0.1", _running(600))
    assert get_run(app_layout.app_name, "0.0.1",
                   storage=_storage(app_layout))["status"] == "running"


# ---------------------------------------------------------------------------
# vmn exp list / show
# ---------------------------------------------------------------------------


def _cli(capfd, app_layout, **kw):
    capfd.readouterr()
    assert _exp(app_layout.app_name, **kw) == 0
    return capfd.readouterr().out


def test_cli_list_and_show_trust_a_fresh_store_write(app_layout, capfd):
    _bootstrap(app_layout)
    _write_run(app_layout, "0.0.1", _running(600))
    _write_run(app_layout, "0.0.2", _running(600), store_age_sec=900)

    lines = _cli(capfd, app_layout, action="list").splitlines()
    assert "running" in next(line for line in lines if "0.0.1" in line)
    assert "stuck" in next(line for line in lines if "0.0.2" in line)

    assert "Status:    running" in _cli(capfd, app_layout, action="show", version="0.0.1")
    assert "Status:    stuck" in _cli(capfd, app_layout, action="show", version="0.0.2")


def test_cli_list_without_a_store_time_uses_the_heartbeat(
    app_layout, capfd, no_store_mtime
):
    _bootstrap(app_layout)
    _write_run(app_layout, "0.0.1", _running(600))

    line = next(
        line for line in _cli(capfd, app_layout, action="list").splitlines()
        if "0.0.1" in line
    )
    assert "stuck" in line


# ---------------------------------------------------------------------------
# prune's live guard
# ---------------------------------------------------------------------------


def _prune(app_layout):
    args = SimpleNamespace(keep=0, older_than=None, force=False)
    return experiment_prune(None, {}, _storage(app_layout), args, app_layout.app_name)


def test_prune_calls_a_run_with_a_fresh_store_write_running(app_layout, capfd):
    _write_run(app_layout, "0.0.1", _running(600))
    _write_run(app_layout, "0.0.2", _running(600), store_age_sec=900)

    assert _prune(app_layout) == 0
    out = capfd.readouterr().out
    assert "Skipping 0.0.1: still running" in out
    assert "Skipping 0.0.2: stuck" in out


def test_prune_without_a_store_time_uses_the_heartbeat(
    app_layout, capfd, no_store_mtime
):
    _write_run(app_layout, "0.0.1", _running(600))

    assert _prune(app_layout) == 0
    assert "Skipping 0.0.1: stuck" in capfd.readouterr().out
