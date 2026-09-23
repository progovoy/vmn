"""SDK run lifecycle under the conditions a real cluster produces.

* several workers cold-starting one fresh checkout at the same moment;
* a container image with no ``.git`` (only an exported snapshot's metadata);
* a flaky remote store — liveness and the workload's own errors must survive it;
* long runs, whose log must reach the remote while they are still going.
"""
import os
import subprocess
import time

import pytest
import yaml
from helpers import _PROJECT_ROOT, _PY, _bootstrap, _storage

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core.experiment_status import load_run_state
from version_stamp.exp import run as run_module
from version_stamp.exp import start_run


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    keys = ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA")
    for key in keys:
        os.environ.pop(key, None)
    yield
    for key in keys:
        os.environ.pop(key, None)


def _child_env(**extra):
    env = dict(os.environ)
    # Keep the caller's PYTHONPATH too: it may carry the import shim that makes
    # this checkout's version_stamp win over an editable install.
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_PROJECT_ROOT, os.environ.get("PYTHONPATH")) if p
    )
    env.update(extra)
    return env


# ---------------------------------------------------------------------------
# parallel cold start
# ---------------------------------------------------------------------------


def test_parallel_cold_start_every_worker_succeeds(app_layout):
    # A fresh repo: no vmn init, no app, no baseline — four workers at once.
    code = (
        "from version_stamp.exp import start_run\n"
        f"with start_run({app_layout.app_name!r}) as run:\n"
        "    run.log_metric('acc', 0.5)\n"
        "print('RUN', run.id)\n"
    )
    env = _child_env(VMN_WORKING_DIR=app_layout.repo_path)
    procs = [
        subprocess.Popen(
            [_PY, "-c", code],
            cwd=app_layout.repo_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    results = [p.communicate(timeout=300) + (p.returncode,) for p in procs]

    failures = [err for _, err, rc in results if rc != 0]
    assert not failures, failures[0]
    ids = {
        line.split()[1]
        for out, _, _ in results
        for line in out.splitlines()
        if line.startswith("RUN ")
    }
    assert len(ids) == 4


# ---------------------------------------------------------------------------
# container mode: no git checkout, an exported snapshot's metadata instead
# ---------------------------------------------------------------------------


@pytest.fixture
def container(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(
        yaml.safe_dump(
            {
                "verstr": "0.0.1-dev.abc1234.def5678",
                "app_name": "trainer",
                "base_version": "0.0.1",
                "base_commit": "abc1234" * 5 + "abcde",
                "branch": "main",
            }
        )
    )
    store = tmp_path / "store"
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store))
    return store


def test_start_run_works_in_a_container_without_git(container):
    with start_run(note="in a container") as run:
        run.log_metric("loss", 0.25)

    assert run.app_name == "trainer"
    assert run.id.startswith("0.0.1-dev.abc1234.def5678")
    storage = get_snapshot_storage(
        "local", vmn_root_path=str(container), subdir="experiments"
    )
    assert [m["verstr"] for m in storage.list_snapshots("trainer")] == [run.id]
    state = load_run_state(storage, "trainer", run.id)
    assert state["exit_code"] == 0
    log = storage.load_merged_log("trainer", run.id)
    assert any(e.get("values", {}).get("loss") == 0.25 for e in log)


def test_container_mode_needs_somewhere_to_write(container, monkeypatch):
    monkeypatch.delenv("VMN_EXPERIMENT_DIR")
    with pytest.raises(ValueError, match="VMN_EXPERIMENT_DIR"):
        start_run()


# ---------------------------------------------------------------------------
# flaky remote: sync cadence, finish() and __exit__ robustness
# ---------------------------------------------------------------------------


class _FlakyStorage:
    """A local storage whose chosen operations can be made to fail."""

    def __init__(self, inner):
        self._inner = inner
        self.fail = set()
        self.syncs = 0

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            if name in self.fail:
                raise ConnectionError(f"S3 503 SlowDown ({name})")
            return attr(*args, **kwargs)

        return call

    def sync_log_to_remote(self, *args, **kwargs):
        self.syncs += 1
        if "sync_log_to_remote" in self.fail:
            raise ConnectionError("S3 503 SlowDown (sync)")


@pytest.fixture
def flaky(app_layout):
    _bootstrap(app_layout)
    return _FlakyStorage(_storage(app_layout))


def _wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_log_is_synced_periodically_while_running(app_layout, flaky):
    with start_run(
        app_layout.app_name,
        storage=flaky,
        heartbeat_interval_sec=0.05,
        sync_interval_sec=0.05,
    ):
        assert _wait_for(lambda: flaky.syncs >= 2)


def test_sync_interval_zero_only_syncs_on_finish(app_layout, flaky):
    with start_run(
        app_layout.app_name,
        storage=flaky,
        heartbeat_interval_sec=0.05,
        sync_interval_sec=0,
    ):
        time.sleep(0.3)
        assert flaky.syncs == 0
    assert flaky.syncs == 1


def test_failing_sync_never_stops_the_heartbeat(app_layout, flaky):
    flaky.fail.add("sync_log_to_remote")
    with start_run(
        app_layout.app_name,
        storage=flaky,
        heartbeat_interval_sec=0.05,
        sync_interval_sec=0.05,
    ) as run:
        first = load_run_state(flaky, app_layout.app_name, run.id)["heartbeat"]
        assert _wait_for(
            lambda: flaky.syncs >= 2
            and load_run_state(flaky, app_layout.app_name, run.id)["heartbeat"]
            != first
        )


def test_finish_survives_a_failing_store(app_layout, flaky):
    run = start_run(app_layout.app_name, storage=flaky)
    flaky.fail.update({"save_file", "append_log_entry", "sync_log_to_remote"})

    run.finish()  # must not raise

    assert run not in run_module._OPEN_RUNS
    assert "VMN_EXPERIMENT_ID" not in os.environ
    assert "VMN_APP_NAME" not in os.environ


def test_workload_exception_is_never_masked_by_the_store(app_layout, flaky):
    class TrainingDiverged(Exception):
        pass

    with pytest.raises(TrainingDiverged):
        with start_run(app_layout.app_name, storage=flaky) as run:
            flaky.fail.update({"save_file", "append_log_entry"})
            raise TrainingDiverged("loss is nan")

    assert run not in run_module._OPEN_RUNS
