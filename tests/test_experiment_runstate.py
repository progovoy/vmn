"""`vmn exp run` publishes live run state; status is derived from it."""
import os
import subprocess
import time

import yaml

from version_stamp.core import experiment_status as st
from version_stamp.core.experiment_status import RUN_STATE_FILE, load_run_state
from helpers import (
    extract_dev_verstr,
    _PROJECT_ROOT,
    _PY,
    _bootstrap,
    _experiment,
    _storage,
)


def _exp_run(app_name, run_cmd, extra=None):
    """`vmn exp run <app> [extra] -- <cmd>` in-process."""
    return _experiment(app_name, action="run", run_cmd=run_cmd, extra_args=extra)


def _run_state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def test_successful_run_finishes_with_exit_code_and_duration(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _exp_run(app_layout.app_name, [_PY, "-c", "print('ok')"]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    state = _run_state(app_layout, verstr)
    assert state["state"] == "finished"
    assert state["exit_code"] == 0
    assert isinstance(state["duration_sec"], (int, float))
    assert state["finished_at"]
    assert state["heartbeat"]
    assert state["pid"] > 0
    assert state["host"]
    assert state["command"][-1] == "print('ok')"
    assert state["heartbeat_interval_sec"] == st.DEFAULT_HEARTBEAT_INTERVAL_SEC
    assert st.derive_status(state) == st.SUCCEEDED


def test_failing_run_derives_failed(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _exp_run(app_layout.app_name, [_PY, "-c", "import sys; sys.exit(4)"]) == 4
    verstr = extract_dev_verstr(capfd.readouterr().out)

    state = _run_state(app_layout, verstr)
    assert state["state"] == "finished"
    assert state["exit_code"] == 4
    assert st.derive_status(state) == st.FAILED


def test_in_flight_run_is_running_with_advancing_heartbeat(app_layout, capfd):
    """The child reads its own run_state mid-run: it must say ``running``."""
    _bootstrap(app_layout)

    script = (
        "import os, time, yaml\n"
        "from version_stamp.cli.snapshot import get_snapshot_storage\n"
        "from version_stamp.cli.experiment import load_run_state\n"
        "time.sleep(2.5)\n"
        "storage = get_snapshot_storage('local',"
        " vmn_root_path=os.environ['VMN_WORKING_DIR'], subdir='experiments')\n"
        "state = load_run_state(storage, os.environ['VMN_APP_NAME'],"
        " os.environ['VMN_EXPERIMENT_ID'])\n"
        "open('probe.yml', 'w').write(yaml.dump(state))\n"
    )
    capfd.readouterr()
    os.environ["PYTHONPATH"] = _PROJECT_ROOT
    try:
        assert (
            _exp_run(
                app_layout.app_name,
                [_PY, "-c", script],
                extra=["--heartbeat-interval", "1"],
            )
            == 0
        )
    finally:
        os.environ.pop("PYTHONPATH", None)
    verstr = extract_dev_verstr(capfd.readouterr().out)

    with open(os.path.join(app_layout.repo_path, "probe.yml")) as f:
        live = yaml.safe_load(f)
    assert live["state"] == "running"
    assert live["exit_code"] is None
    assert live["heartbeat_interval_sec"] == 1
    assert live["heartbeat"] > live["started_at"], "heartbeat never refreshed"
    assert st.derive_status(live) == st.RUNNING

    assert _run_state(app_layout, verstr)["state"] == "finished"


def test_sigkilled_runner_leaves_running_state_that_goes_stuck(app_layout):
    _bootstrap(app_layout)

    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env["PYTHONPATH"] = _PROJECT_ROOT
    runner = subprocess.Popen(
        [
            _PY,
            "-m",
            "version_stamp.cli.entry",
            "exp",
            "run",
            app_layout.app_name,
            "--heartbeat-interval",
            "1",
            "--",
            _PY,
            "-c",
            "import time; time.sleep(60)",
        ],
        cwd=app_layout.repo_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    storage = _storage(app_layout)
    state = None
    verstr = None
    deadline = time.time() + 60
    while time.time() < deadline:
        for meta in storage.list_snapshots(app_layout.app_name):
            candidate = load_run_state(
                storage, app_layout.app_name, meta["verstr"]
            )
            if candidate:
                verstr, state = meta["verstr"], candidate
                break
        if state:
            break
        time.sleep(0.5)

    assert state is not None, "run_state.yml never appeared"
    runner.kill()
    runner.wait(timeout=30)
    if state.get("pid"):
        try:
            os.kill(state["pid"], 9)
        except OSError:
            pass

    state = load_run_state(storage, app_layout.app_name, verstr)
    assert state["state"] == "running"
    assert state["exit_code"] is None
    assert st.derive_status(state) == st.RUNNING

    # Fixture setup: age the heartbeat past the staleness window.
    state["heartbeat"] = "2020-01-01T00:00:00Z"
    storage.save_file(
        app_layout.app_name, verstr, RUN_STATE_FILE, yaml.dump(state, sort_keys=False)
    )
    assert st.derive_status(load_run_state(storage, app_layout.app_name, verstr)) == (
        st.STUCK
    )


def test_created_experiment_has_no_run_state(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="never run") == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    assert _run_state(app_layout, verstr) is None
    assert st.derive_status(None) == st.CREATED


def test_load_run_state_tolerates_corrupt_file(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    storage = _storage(app_layout)
    storage.save_file(app_layout.app_name, verstr, RUN_STATE_FILE, "{{ not yaml")
    assert load_run_state(storage, app_layout.app_name, verstr) is None


def test_unspawnable_command_leaves_no_running_state(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _exp_run(app_layout.app_name, ["vmn-no-such-binary-xyz"]) == 1
    capfd.readouterr()

    storage = _storage(app_layout)
    for meta in storage.list_snapshots(app_layout.app_name):
        state = load_run_state(storage, app_layout.app_name, meta["verstr"])
        assert state is None or state.get("state") != "running"


def test_exp_list_shows_status(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _exp_run(app_layout.app_name, [_PY, "-c", "print('done')"]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    out = capfd.readouterr().out
    assert verstr in out
    assert st.SUCCEEDED in out


def test_exp_show_prints_status_block(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _exp_run(app_layout.app_name, [_PY, "-c", "import sys; sys.exit(2)"]) == 2
    verstr = extract_dev_verstr(capfd.readouterr().out)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=verstr) == 0
    out = capfd.readouterr().out
    assert "Status:" in out
    assert st.FAILED in out
    assert "Exit code:" in out
    assert "Duration:" in out
