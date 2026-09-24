"""Under DDP/torchrun/SLURM only rank 0 records a run.

Every rank of a distributed job runs the same script, so without this each of N
ranks would snapshot the repo, claim its own verstr and heartbeat — N runs for
one job. A non-zero rank gets a no-op run with the same interface instead.
"""
import os
import threading

import pytest
from helpers import _bootstrap, _storage

from version_stamp.exp import NoOpRun, Run, current_run, start_run

_RANK_KEYS = ("RANK", "LOCAL_RANK", "WORLD_SIZE", "SLURM_PROCID")


@pytest.fixture(autouse=True)
def _clean_rank_env(monkeypatch):
    for key in _RANK_KEYS + ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


def _heartbeat_threads():
    return [t for t in threading.enumerate() if t.name == "vmn-heartbeat"]


@pytest.mark.parametrize(
    "env",
    [
        {"RANK": "1"},
        {"RANK": "3", "LOCAL_RANK": "0", "WORLD_SIZE": "4"},
        {"LOCAL_RANK": "1", "WORLD_SIZE": "2"},
        {"SLURM_PROCID": "2"},
    ],
)
def test_non_zero_rank_gets_a_noop_run(app_layout, monkeypatch, env):
    _bootstrap(app_layout)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with start_run(app_layout.app_name, params={"lr": 0.1}) as run:
        assert isinstance(run, NoOpRun)
        assert run.id is None
        assert current_run() is None
        assert not _heartbeat_threads()
        run.log_metric("loss", 1.0, step=1)
        run.log_metrics({"acc": 0.5})
        run.log_params({"seed": 1})
        run.log_note("hi")
        run.log_artifact("does-not-matter.bin")
    run.finish()

    assert "VMN_EXPERIMENT_ID" not in os.environ
    assert _storage(app_layout).list_snapshots(app_layout.app_name) == []


def test_noop_run_needs_no_git_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("RANK", "1")
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    run = start_run("anything")

    assert isinstance(run, NoOpRun)
    assert run.app_name == "anything"


@pytest.mark.parametrize(
    "env",
    [
        {"RANK": "0", "WORLD_SIZE": "4"},
        {"LOCAL_RANK": "1", "WORLD_SIZE": "1"},
        {"SLURM_PROCID": "0"},
        {"RANK": "not-a-number"},
    ],
)
def test_rank_zero_and_single_process_record_normally(app_layout, monkeypatch, env):
    _bootstrap(app_layout)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with start_run(app_layout.app_name) as run:
        assert isinstance(run, Run)
        assert os.environ["VMN_EXPERIMENT_ID"] == run.id

    verstrs = [m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)]
    assert verstrs == [run.id]


def test_all_ranks_opts_out_of_the_noop(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("RANK", "2")

    with start_run(app_layout.app_name, all_ranks=True) as run:
        assert isinstance(run, Run)
        assert run.id

    assert len(_storage(app_layout).list_snapshots(app_layout.app_name)) == 1
