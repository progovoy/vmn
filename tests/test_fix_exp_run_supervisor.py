"""`vmn exp run` supervision survives flaky storage and runs where the user is.

A heartbeat PUT that fails, a metrics line that cannot be ingested or a remote
sync that raises must never kill the supervisor — that orphans the child and
leaves the run claiming ``running`` forever.
"""

import os
import subprocess
import time

from helpers import (
    _PROJECT_ROOT,
    _PY,
    _bootstrap,
    _experiment,
    _storage,
    extract_dev_verstr,
)

from version_stamp.cli import experiment_run as runmod
from version_stamp.cli.snapshot import CachedSnapshotStorage, LocalSnapshotStorage
from version_stamp.core import experiment_status as st
from version_stamp.core.experiment_status import RUN_STATE_FILE, load_run_state


def _exp_run(app_name, run_cmd, extra=None):
    return _experiment(app_name, action="run", run_cmd=run_cmd, extra_args=extra)


def _run_state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def test_failing_heartbeat_writes_do_not_kill_the_supervisor(
    app_layout, capfd, monkeypatch
):
    _bootstrap(app_layout)
    real = LocalSnapshotStorage.save_file
    live_writes = []
    failures = []

    def flaky(self, app_name, verstr, filename, data):
        if filename == RUN_STATE_FILE and "state: running" in str(data):
            live_writes.append(filename)
            # The initial publish lands; the next three heartbeats fail.
            if 2 <= len(live_writes) <= 4:
                failures.append(filename)
                raise ConnectionError("S3 503 SlowDown")
        return real(self, app_name, verstr, filename, data)

    monkeypatch.setattr(LocalSnapshotStorage, "save_file", flaky)

    capfd.readouterr()
    code = _exp_run(
        app_layout.app_name,
        [_PY, "-c", "import time; time.sleep(3.5)"],
        extra=["--heartbeat-interval", "1"],
    )
    verstr = extract_dev_verstr(capfd.readouterr().out)

    assert failures, "the fixture never injected a heartbeat failure"
    assert code == 0
    state = _run_state(app_layout, verstr)
    assert state["exit_code"] == 0
    assert st.derive_status(state) == st.SUCCEEDED


def test_failing_metric_ingestion_does_not_kill_the_supervisor(
    app_layout, capfd, monkeypatch
):
    _bootstrap(app_layout)
    real = LocalSnapshotStorage.append_log_entry
    raised = []

    def flaky(self, app_name, verstr, writer_id, entry):
        if entry.get("type") == "metrics" and not raised:
            raised.append(entry)
            raise OSError("disk full")
        return real(self, app_name, verstr, writer_id, entry)

    monkeypatch.setattr(LocalSnapshotStorage, "append_log_entry", flaky)
    script = (
        "import os, time\n"
        "p = os.environ['VMN_METRICS_FILE']\n"
        "open(p, 'a').write('loss=0.9\\n'); time.sleep(1.5)\n"
        "open(p, 'a').write('loss=0.5\\n'); time.sleep(1.5)\n"
    )

    capfd.readouterr()
    assert _exp_run(app_layout.app_name, [_PY, "-c", script]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    assert raised, "the fixture never injected an ingestion failure"
    losses = [
        e["values"]["loss"] for e in _log(app_layout, verstr) if e["type"] == "metrics"
    ]
    assert losses == [0.5]
    assert _run_state(app_layout, verstr)["exit_code"] == 0


def test_failing_remote_sync_does_not_kill_the_supervisor(
    app_layout, capfd, monkeypatch
):
    _bootstrap(app_layout)
    calls = []

    def broken_sync(self, app_name, verstr, writer_id):
        calls.append(verstr)
        raise ConnectionError("network down")

    monkeypatch.setattr(CachedSnapshotStorage, "sync_log_to_remote", broken_sync)

    capfd.readouterr()
    code = _exp_run(
        app_layout.app_name,
        [_PY, "-c", "import time; time.sleep(2.5)"],
        extra=["--sync-interval", "1"],
    )
    verstr = extract_dev_verstr(capfd.readouterr().out)

    assert calls, "sync was never attempted"
    assert code == 0
    assert _run_state(app_layout, verstr)["exit_code"] == 0
    assert any(e["type"] == "run" for e in _log(app_layout, verstr))


def test_slow_remote_sync_does_not_starve_heartbeats(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setattr(runmod, "_FINAL_SYNC_TIMEOUT_SEC", 1)

    def slow_sync(self, app_name, verstr, writer_id):
        time.sleep(6)

    monkeypatch.setattr(CachedSnapshotStorage, "sync_log_to_remote", slow_sync)
    beats = []
    real = LocalSnapshotStorage.save_file

    def counting(self, app_name, verstr, filename, data):
        if filename == RUN_STATE_FILE and "state: running" in str(data):
            beats.append(time.monotonic())
        return real(self, app_name, verstr, filename, data)

    monkeypatch.setattr(LocalSnapshotStorage, "save_file", counting)

    capfd.readouterr()
    started = time.monotonic()
    code = _exp_run(
        app_layout.app_name,
        [_PY, "-c", "import time; time.sleep(4.5)"],
        extra=["--sync-interval", "1", "--heartbeat-interval", "1"],
    )
    elapsed = time.monotonic() - started

    assert code == 0
    # One initial publish plus a beat per second: a sync blocking the loop for
    # 6s would allow at most the initial one and a single beat.
    assert len(beats) >= 4, beats
    # The final sync is bounded by its timeout rather than the slow upload.
    assert elapsed < 4.5 + 6 + 4


def _env_without_working_dir(app_layout):
    env = dict(os.environ)
    env.pop("VMN_WORKING_DIR", None)
    env.pop("VMN_EXPERIMENT_ID", None)
    env.pop("VMN_APP_NAME", None)
    env["PYTHONPATH"] = _PROJECT_ROOT
    return env


def test_child_runs_in_the_invocation_directory(app_layout):
    _bootstrap(app_layout)
    src = os.path.join(app_layout.repo_path, "src")
    os.makedirs(src)
    with open(os.path.join(src, "train.py"), "w") as f:
        f.write("import os\nopen('cwd.txt', 'w').write(os.getcwd())\n")

    proc = subprocess.run(
        [
            _PY,
            "-m",
            "version_stamp.cli.entry",
            "exp",
            "run",
            app_layout.app_name,
            "--",
            _PY,
            "train.py",
        ],
        cwd=src,
        env=_env_without_working_dir(app_layout),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    with open(os.path.join(src, "cwd.txt")) as f:
        assert os.path.realpath(f.read()) == os.path.realpath(src)


def test_vmn_working_dir_is_the_childs_cwd_when_set(app_layout, capfd):
    _bootstrap(app_layout)
    target = os.path.join(app_layout.repo_path, "cwd.txt")

    capfd.readouterr()
    code = _exp_run(
        app_layout.app_name,
        [_PY, "-c", "import os; open('cwd.txt', 'w').write(os.getcwd())"],
    )

    assert code == 0
    with open(target) as f:
        assert os.path.realpath(f.read()) == os.path.realpath(
            os.environ["VMN_WORKING_DIR"]
        )
