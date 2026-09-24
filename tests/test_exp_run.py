"""The in-process experiment SDK: ``from version_stamp.exp import start_run``.

An SDK run must be indistinguishable on disk from a ``vmn exp run`` run — same
verstr scheme, same ``metadata.yml``, same per-writer log, same
``run_state.yml`` — so every reader (``vmn exp list/show``, the dashboard) works
on it with no changes.
"""
import logging
import os
import subprocess
import sys
import time

import pytest
import yaml

from version_stamp.core import experiment_status as st
from version_stamp.core.constants import VMN_USER_NAME
from version_stamp.core.experiment_status import RUN_STATE_FILE, load_run_state
from version_stamp.exp import Run, start_run
from helpers import (
    extract_dev_verstr,
    _PROJECT_ROOT,
    _PY,
    _bootstrap,
    _experiment,
    _storage,
)

_RUN_STATE_KEYS = {
    "state",
    "command",
    "pid",
    "host",
    "started_at",
    "heartbeat",
    "heartbeat_interval_sec",
    "heartbeat_seq",
    "exit_code",
    "finished_at",
    "duration_sec",
}


def _state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def _meta(app_layout, verstr):
    meta, _ = _storage(app_layout).load(app_layout.app_name, verstr)
    return meta


def _sdk_script(app_name, body):
    """A python -c program that drives the SDK with no vmn CLI involvement."""
    return "from version_stamp.exp import start_run\nAPP = %r\n%s" % (app_name, body)


def _run_python(app_layout, script):
    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env["PYTHONPATH"] = _PROJECT_ROOT
    env.pop("VMN_EXPERIMENT_ID", None)
    return subprocess.run(
        [_PY, "-c", script],
        cwd=app_layout.repo_path,
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def test_clean_context_manager_run_derives_succeeded(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, note="sdk run") as run:
        assert isinstance(run, Run)
        assert run.app_name == app_layout.app_name
        assert run.id
        verstr = run.id
        live = _state(app_layout, verstr)
        assert live["state"] == "running"
        assert live["exit_code"] is None
        assert st.derive_status(live) == st.RUNNING

    state = _state(app_layout, verstr)
    assert state["state"] == "finished"
    assert state["exit_code"] == 0
    assert state["finished_at"]
    assert isinstance(state["duration_sec"], (int, float))
    assert state["pid"] == os.getpid()
    assert state["host"]
    assert state["command"] == list(sys.argv)
    assert state["heartbeat_interval_sec"] == st.DEFAULT_HEARTBEAT_INTERVAL_SEC
    assert st.derive_status(state) == st.SUCCEEDED

    assert _meta(app_layout, verstr)["note"] == "sdk run"

    terminal = [e for e in _log(app_layout, verstr) if e.get("type") == "run"]
    assert len(terminal) == 1
    assert terminal[0]["exit_code"] == 0
    assert terminal[0]["duration_sec"] == state["duration_sec"]


def test_explicit_finish_records_a_failing_exit_code(app_layout):
    _bootstrap(app_layout)

    run = start_run(app_layout.app_name)
    run.finish(exit_code=3)

    state = _state(app_layout, run.id)
    assert state["exit_code"] == 3
    assert st.derive_status(state) == st.FAILED


def test_exception_is_reraised_and_recorded(app_layout):
    _bootstrap(app_layout)

    holder = {}
    with pytest.raises(ValueError, match="boom"):
        with start_run(app_layout.app_name) as run:
            holder["id"] = run.id
            raise ValueError("boom")

    verstr = holder["id"]
    state = _state(app_layout, verstr)
    assert state["state"] == "finished"
    assert state["exit_code"] == 1
    assert st.derive_status(state) == st.FAILED

    errors = [e for e in _log(app_layout, verstr) if e.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["exception"] == "ValueError"
    assert "boom" in errors[0]["message"]


def test_finish_twice_does_not_double_append_or_corrupt_state(app_layout):
    _bootstrap(app_layout)

    run = start_run(app_layout.app_name)
    run.finish()
    first = _state(app_layout, run.id)
    run.finish(exit_code=9)
    second = _state(app_layout, run.id)

    assert second == first
    assert second["exit_code"] == 0
    assert len([e for e in _log(app_layout, run.id) if e.get("type") == "run"]) == 1


def test_exiting_a_finished_run_context_is_a_no_op(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as run:
        run.finish(exit_code=5)

    assert _state(app_layout, run.id)["exit_code"] == 5


# ---------------------------------------------------------------------------
# heartbeat / staleness
# ---------------------------------------------------------------------------


def test_heartbeat_refreshes_run_state_while_open(app_layout):
    _bootstrap(app_layout)

    run = start_run(app_layout.app_name, heartbeat_interval_sec=1)
    try:
        started = _state(app_layout, run.id)["started_at"]
        deadline = time.time() + 20
        while time.time() < deadline:
            if _state(app_layout, run.id)["heartbeat"] > started:
                break
            time.sleep(0.25)
        live = _state(app_layout, run.id)
        assert live["heartbeat_interval_sec"] == 1
        assert live["heartbeat"] > started, "heartbeat never refreshed"
        assert st.derive_status(live) == st.RUNNING
    finally:
        run.finish()


def test_run_whose_heartbeat_went_stale_derives_stuck(app_layout):
    """A SIGKILLed SDK process cannot finalize: staleness must report it."""
    _bootstrap(app_layout)

    run = start_run(app_layout.app_name, heartbeat_interval_sec=1)
    try:
        storage = _storage(app_layout)
        state = _state(app_layout, run.id)
        assert st.derive_status(state) == st.RUNNING

        # Fixture setup: age the heartbeat past the staleness window.
        state["heartbeat"] = "2020-01-01T00:00:00Z"
        state["started_at"] = "2020-01-01T00:00:00Z"
        storage.save_file(
            app_layout.app_name,
            run.id,
            RUN_STATE_FILE,
            yaml.dump(state, sort_keys=False),
        )
        aged = load_run_state(storage, app_layout.app_name, run.id)
        assert st.derive_status(aged) == st.STUCK
    finally:
        run.finish()


# ---------------------------------------------------------------------------
# logging entries
# ---------------------------------------------------------------------------


def test_metrics_notes_and_artifacts_land_in_the_log(app_layout):
    _bootstrap(app_layout)

    artifact = os.path.join(app_layout.repo_path, "weights.bin")
    with open(artifact, "wb") as f:
        f.write(b"0123456789")

    with start_run(app_layout.app_name) as run:
        run.log_metric("loss", 0.5)
        run.log_metric("loss", 0.25, step=2)
        run.log_metrics({"acc": 0.9, "f1": 0.8}, step=2)
        run.log_note("looks good")
        run.log_artifact(artifact)

    log = _log(app_layout, run.id)
    metrics = [e for e in log if e.get("type") == "metrics"]
    assert metrics[0]["values"] == {"loss": 0.5}
    assert "step" not in metrics[0]
    assert metrics[1]["values"] == {"loss": 0.25}
    assert metrics[1]["step"] == 2
    assert metrics[2]["values"] == {"acc": 0.9, "f1": 0.8}
    assert metrics[2]["step"] == 2

    notes = [e for e in log if e.get("type") == "note"]
    assert notes[0]["text"] == "looks good"

    artifacts = [e for e in log if e.get("type") == "artifact"]
    assert artifacts[0]["path"] == "weights.bin"
    assert artifacts[0]["size"] == 10

    from version_stamp.cli.experiment import _get_latest_metrics

    assert _get_latest_metrics(log)["loss"] == 0.25


def test_creation_params_ride_the_create_entry_like_the_cli_file_path(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, params={"lr": 0.001, "batch": 32}) as run:
        pass

    log = _log(app_layout, run.id)
    create = next(e for e in log if e.get("type") == "create")
    assert create["params"] == {"lr": 0.001, "batch": 32}

    from version_stamp.cli.experiment import _create_entry_params, _get_latest_metrics

    assert _create_entry_params(log) == {"lr": 0.001, "batch": 32}
    assert _get_latest_metrics(log)["lr"] == 0.001


def test_log_params_after_creation_appends_a_params_entry(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as run:
        run.log_params({"optimizer": "adam", "lr": 0.01})

    entries = [e for e in _log(app_layout, run.id) if e.get("type") == "params"]
    assert len(entries) == 1
    assert entries[0]["params"] == {"optimizer": "adam", "lr": 0.01}
    assert entries[0]["timestamp"]


def test_log_artifact_rejects_a_missing_file(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as run:
        with pytest.raises(FileNotFoundError):
            run.log_artifact(os.path.join(app_layout.repo_path, "nope.bin"))


# ---------------------------------------------------------------------------
# CLI compatibility
# ---------------------------------------------------------------------------


def test_exp_show_renders_an_sdk_run_unchanged(app_layout, capfd):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, note="from the sdk") as run:
        run.log_metric("loss", 0.125)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=run.id) == 0
    out = capfd.readouterr().out
    assert run.id in out
    assert "from the sdk" in out
    assert "Status:" in out
    assert st.SUCCEEDED in out
    assert "Exit code: 0" in out
    assert "Duration:" in out
    assert f"Runner:    pid {os.getpid()}" in out
    assert "loss: 0.125" in out


def test_exp_list_renders_an_sdk_run_unchanged(app_layout, capfd):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as run:
        run.log_metric("acc", 0.75)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    out = capfd.readouterr().out
    assert run.id in out
    assert st.SUCCEEDED in out
    assert "acc=0.75" in out


def test_sdk_and_cli_records_share_one_schema(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert (
        _experiment(
            app_layout.app_name, action="run", run_cmd=[_PY, "-c", "print('ok')"]
        )
        == 0
    )
    cli_verstr = extract_dev_verstr(capfd.readouterr().out)

    with start_run(app_layout.app_name) as run:
        pass

    cli_state = _state(app_layout, cli_verstr)
    sdk_state = _state(app_layout, run.id)
    assert set(sdk_state) == set(cli_state) == _RUN_STATE_KEYS

    assert set(_meta(app_layout, run.id)) == set(_meta(app_layout, cli_verstr))

    # Same verstr scheme: both are dev verstrs off the same code state, so the
    # SDK run is the next .rN allocation.
    from helpers import DEV_VERSION_RE

    assert DEV_VERSION_RE.match(run.id)
    assert run.id != cli_verstr
    assert run.id.rsplit(".r", 1)[0] == cli_verstr.rsplit(".r", 1)[0]


def test_sdk_writes_the_same_per_writer_log_file_as_the_cli(app_layout):
    _bootstrap(app_layout)

    from version_stamp.cli.experiment import _get_writer_id

    with start_run(app_layout.app_name) as run:
        run.log_metric("loss", 1.0)

    log_path = os.path.join(
        app_layout.repo_path,
        ".vmn",
        app_layout.app_name,
        "experiments",
        run.id.replace("+", "_plus_"),
        f"log.{_get_writer_id()}.jsonl",
    )
    assert os.path.isfile(log_path), os.listdir(os.path.dirname(log_path))


# ---------------------------------------------------------------------------
# app name resolution
# ---------------------------------------------------------------------------


def test_app_name_is_resolved_from_the_repo_when_omitted(app_layout):
    _bootstrap(app_layout)
    os.environ.pop("VMN_APP_NAME", None)

    with start_run() as run:
        assert run.app_name == app_layout.app_name

    assert _state(app_layout, run.id)["exit_code"] == 0


def test_app_name_env_var_is_honoured(app_layout):
    _bootstrap(app_layout)

    os.environ["VMN_APP_NAME"] = app_layout.app_name
    try:
        with start_run() as run:
            assert run.app_name == app_layout.app_name
    finally:
        os.environ.pop("VMN_APP_NAME", None)


def test_the_write_and_read_sides_share_one_resolver():
    """One rule, one implementation — two copies would drift apart."""
    import version_stamp.exp as exp_pkg
    import version_stamp.exp.reader as reader_mod
    import version_stamp.exp.run as run_mod

    assert run_mod._resolve_app_name is exp_pkg._resolve_app_name
    assert reader_mod._resolve_app_name is exp_pkg._resolve_app_name


def test_ambiguous_app_name_error_names_the_candidates():
    from version_stamp.exp import _resolve_app_name

    os.environ.pop("VMN_APP_NAME", None)
    with pytest.raises(ValueError) as exc:
        _resolve_app_name(None, lambda: ["alpha", "beta"])

    message = str(exc.value)
    assert "alpha" in message and "beta" in message
    assert "app_name=" in message


# ---------------------------------------------------------------------------
# the VMN_LOGGER public entry point the SDK needs
# ---------------------------------------------------------------------------


@pytest.fixture
def pristine_vmn_logger():
    """A VMN_LOGGER with no handlers and no holder, restored afterwards."""
    from version_stamp.core import logging as vmn_logging

    logger = logging.getLogger(VMN_USER_NAME)
    saved_handlers = list(logger.handlers)
    was_initialized = bool(vmn_logging.VMN_LOGGER)

    logger.handlers[:] = []
    vmn_logging.reset_logger()
    yield vmn_logging

    logger.handlers[:] = saved_handlers
    vmn_logging.reset_logger()
    if was_initialized:
        vmn_logging.ensure_logger()


def test_ensure_logger_installs_a_handlerless_logger(pristine_vmn_logger):
    vmn_logging = pristine_vmn_logger

    logger = vmn_logging.ensure_logger()

    assert isinstance(logger, logging.Logger)
    assert logger.name == VMN_USER_NAME
    assert logger.handlers == [], "a library must not configure handlers"
    assert bool(vmn_logging.VMN_LOGGER)
    vmn_logging.VMN_LOGGER.warning("must not raise AttributeError")


def test_ensure_logger_is_idempotent(pristine_vmn_logger):
    vmn_logging = pristine_vmn_logger

    first = vmn_logging.ensure_logger()
    second = vmn_logging.ensure_logger()

    assert first is second
    assert first.handlers == []


def test_ensure_logger_leaves_an_initialized_cli_logger_alone(pristine_vmn_logger):
    vmn_logging = pristine_vmn_logger
    vmn_logging.init_stamp_logger()
    cli_handlers = list(logging.getLogger(VMN_USER_NAME).handlers)
    assert cli_handlers, "init_stamp_logger is expected to install handlers"

    vmn_logging.ensure_logger()

    assert list(logging.getLogger(VMN_USER_NAME).handlers) == cli_handlers


# ---------------------------------------------------------------------------
# no CLI, no logger init
# ---------------------------------------------------------------------------


def test_sdk_runs_in_a_bare_python_process(app_layout):
    """No CLI, so no init_stamp_logger: nothing may touch the VMN_LOGGER proxy."""
    _bootstrap(app_layout)

    proc = _run_python(
        app_layout,
        _sdk_script(
            app_layout.app_name,
            "with start_run(APP, params={'lr': 0.1}) as run:\n"
            "    run.log_metric('loss', 0.5)\n"
            "    run.log_note('bare process')\n"
            "print(run.id)\n",
        ),
    )
    assert proc.returncode == 0, proc.stderr
    assert "AttributeError" not in proc.stderr, proc.stderr
    assert "VMN_LOGGER" not in proc.stderr, proc.stderr

    verstr = proc.stdout.strip().splitlines()[-1]
    state = _state(app_layout, verstr)
    assert st.derive_status(state) == st.SUCCEEDED
    assert [e for e in _log(app_layout, verstr) if e.get("type") == "note"]


def test_atexit_finalizes_a_run_that_was_never_finished(app_layout):
    _bootstrap(app_layout)

    proc = _run_python(
        app_layout,
        _sdk_script(
            app_layout.app_name,
            "import sys\n"
            "run = start_run(APP)\n"
            "print(run.id)\n"
            "sys.stdout.flush()\n"
            "sys.exit(0)\n",
        ),
    )
    assert proc.returncode == 0, proc.stderr

    verstr = proc.stdout.strip().splitlines()[-1]
    state = _state(app_layout, verstr)
    assert state["state"] == "finished", "a forgotten run must not stay running"
    assert state["exit_code"] != 0
    assert st.derive_status(state) == st.FAILED
