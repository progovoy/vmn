"""In-process job actions on store workspaces (plan 11 §7.1, phase 3d).

Each action, run as a store job, must leave the store exactly as the CLI
leaves an identical store (timestamps and writer ids aside).
"""
import os
import argparse
import threading
import time
from types import SimpleNamespace

import pytest

from job_wait import HANG_SEC, wait_job
from vmn_exp.cli.manage import experiment_manage
from vmn_exp.cli.rewind import experiment_rewind
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log
from vmn_exp.cli.model_cmd import model_run_without_repo
from vmn_exp.cli.model_parser import add_model_parser
from vmn_exp.registry.log import read_entries
from vmn_exp.storage.areas import RUNS
from vmn_exp.storage.open import open_storage
from vmn_exp.ui.jobs import MAX_ARCHIVE_BATCH, JobRunner, start_daemon
from vmn_exp.ui.jobs_store import STORE_ACTIONS, build_store_action
from vmn_exp.cli.checkout_store import CwdCheckout
from vmn_exp.core.real_io import RealClock, RealProcesses, RealRandom, real_io
from writer_args import process_writer

APP = "my_app"
V = "0.0.1-dev.abc.def"
_VOLATILE = {"timestamp", "ts", "writer", "writer_id", "actor", "seq", "created_at"}


def _store(tmp_path, name):
    uri = f"file://{tmp_path}/{name}"
    storage = open_storage(uri, area=RUNS, clock=RealClock(), env=os.environ)
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    for step in range(5):
        append_to_log(storage, APP, V, create_log_entry("metrics", values={"loss": step}, step=step), writer=process_writer())
    storage.save_file(APP, V, "model.bin", b"weights")
    flush_log(storage, APP, V, writer=process_writer())
    return uri, storage


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _run_state(storage):
    meta = storage.load_metadata(APP, V)
    return _strip({"archived": meta.get("archived"), "log": storage.load_merged_log(APP, V)})


def _model_state(storage, model="m"):
    return _strip(read_entries(storage, model)) if model else None


def _job(tmp_path, action, body):
    uri, storage = _store(tmp_path, "job")
    job, err = build_store_action(action, APP, body, env=real_io().env, host=real_io().host)
    assert err is None
    touched = []
    job.run(storage, lambda app, verstr: touched.append((app, verstr)), RealClock().now())
    return storage, touched


def _cli_store(tmp_path):
    return _store(tmp_path, "cli")


def _model_cli(uri, *argv):
    parser = argparse.ArgumentParser()
    add_model_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["model", *argv, "--store", uri])
    assert model_run_without_repo(args, real_io(), CwdCheckout()) == 0


def _manage(storage, action, refs, remove=None):
    args = SimpleNamespace(action=action, refs=refs, version=None, latest=False, remove=remove)
    assert experiment_manage(APP, storage, args, writer=process_writer()) == 0


def test_tag_matches_the_cli(tmp_path):
    storage, touched = _job(tmp_path, "exp_tag", {"verstr": V, "set": {"k": "v"}, "remove": ["old"]})
    _, cli = _cli_store(tmp_path)
    _manage(cli, "tag", [V, "k=v"], remove=["old"])
    assert _run_state(storage) == _run_state(cli)
    assert touched == [(APP, V)]


def test_note_matches_the_cli(tmp_path):
    storage, _ = _job(tmp_path, "note", {"verstr": V, "note": "looks good"})
    _, cli = _cli_store(tmp_path)
    append_to_log(cli, APP, V, create_log_entry("note", text="looks good"), writer=process_writer())
    flush_log(cli, APP, V, writer=process_writer())
    assert _run_state(storage) == _run_state(cli)


@pytest.mark.parametrize("verb", ["archive", "unarchive"])
def test_archive_matches_the_cli(tmp_path, verb):
    storage, _ = _job(tmp_path, f"exp_{verb}", {"verstrs": [V]})
    _, cli = _cli_store(tmp_path)
    _manage(cli, verb, [V])
    assert _run_state(storage) == _run_state(cli)


def test_rewind_matches_the_cli(tmp_path):
    storage, touched = _job(tmp_path, "exp_rewind", {"verstr": V, "step": 2})
    _, cli = _cli_store(tmp_path)
    args = SimpleNamespace(version=[V], latest=False, step=2)
    assert experiment_rewind(cli, APP, args, RealClock(), writer=process_writer()) == 0
    assert _run_state(storage) == _run_state(cli)
    assert touched == [(APP, V)]


def test_model_register_alias_deprecate_match_the_cli(tmp_path):
    uri, storage = _store(tmp_path, "job")
    for action, body in [
        ("model_register", {"model": "m", "run": {"app": APP, "verstr": V},
                            "artifact_path": "model.bin", "alias": "prod"}),
        ("model_alias", {"model": "m", "alias": "staging", "version": 1}),
        ("model_deprecate", {"model": "m", "version": 1}),
    ]:
        job, err = build_store_action(action, APP, body, env=real_io().env, host=real_io().host)
        assert err is None, err
        job.run(storage, lambda *_: None, RealClock().now())
    cli_uri, cli = _cli_store(tmp_path)
    _model_cli(cli_uri, "register", "m", "-v", V, "--app", APP, "--artifact", "model.bin",
               "--alias", "prod")
    _model_cli(cli_uri, "alias", "m", "staging", "1")
    _model_cli(cli_uri, "deprecate", "m", "1")
    assert _model_state(storage) == _model_state(cli)


@pytest.mark.parametrize("action", ["prune", "exp_push", "stamp", "goto", "restore", "rerun",
                                    "model_delete", "exp_create"])
def test_destructive_and_git_actions_are_not_offered(action):
    assert action not in STORE_ACTIONS
    job, err = build_store_action(action, APP, {"verstr": V}, env=real_io().env, host=real_io().host)
    assert job is None and err


@pytest.mark.parametrize("action,body", [
    ("exp_tag", {"verstr": "-rf", "set": {"k": "v"}}),
    ("exp_rewind", {"verstr": V, "step": -1}),
    ("note", {"verstr": V}),
    ("model_alias", {"model": "m", "alias": "a", "version": 0}),
])
def test_bad_bodies_are_rejected(action, body):
    job, err = build_store_action(action, APP, body, env=real_io().env, host=real_io().host)
    assert job is None and err


def test_failed_action_marks_the_job_failed(tmp_path):
    _, storage = _store(tmp_path, "job")
    job, _ = build_store_action("exp_tag", APP, {"verstr": "0.0.9-dev.x.y", "set": {"k": "v"}}, env=real_io().env, host=real_io().host)
    runner = JobRunner(processes=RealProcesses(), random=RealRandom(), start_thread=start_daemon)
    submitted, err = runner.submit_call("ws", job.command, lambda: job.run(storage, lambda *_: None, RealClock().now()))
    assert err is None
    done = _wait(runner, submitted["id"])
    assert done["status"] == "failed" and "not found" in done["log"]


def _held_call(gate, entered=None):
    """A store call that hangs until *gate* is set (at most 30 s)."""
    def call():
        if entered is not None:
            entered.set()
        gate.wait(30)
        return "late"
    return call


def test_an_in_process_job_past_the_timeout_reads_failed():
    gate, runner = threading.Event(), JobRunner(timeout_sec=0, processes=RealProcesses(), random=RealRandom(), start_thread=start_daemon)
    try:
        submitted, err = runner.submit_call("ws", ["note"], _held_call(gate))
        assert err is None
        done = _wait(runner, submitted["id"])
        assert done["status"] == "failed" and done["exit_code"] == -1
        assert "Job timed out after 0s" in done["log"]
        assert "the store did not answer" in done["log"]
    finally:
        gate.set()


def test_the_workspace_slot_stays_taken_until_the_call_returns():
    gate, runner = threading.Event(), JobRunner(timeout_sec=0, processes=RealProcesses(), random=RealRandom(), start_thread=start_daemon)
    submitted, _ = runner.submit_call("ws", ["note"], _held_call(gate))
    _wait(runner, submitted["id"])
    assert runner.submit_call("ws", ["note"], lambda: "ok")[1] is not None
    gate.set()
    job = _submit_when_free(runner, "ws", lambda: "ok")
    assert _wait(runner, job["id"])["status"] == "succeeded"


def test_a_submit_behind_a_timed_out_call_says_the_store_is_slow():
    gate, runner = threading.Event(), JobRunner(timeout_sec=0, processes=RealProcesses(), random=RealRandom(), start_thread=start_daemon)
    try:
        submitted, _ = runner.submit_call("ws", ["note"], _held_call(gate))
        _wait(runner, submitted["id"])
        _, err = runner.submit_call("ws", ["note"], lambda: "ok")
        assert err == "The previous action is still waiting for the store"
    finally:
        gate.set()


def test_a_bulk_job_bounds_each_batch_and_stops_after_a_timed_out_one():
    gate, entered, runner, acted = threading.Event(), threading.Event(), JobRunner(timeout_sec=0, processes=RealProcesses(), random=RealRandom(), start_thread=start_daemon), []

    def act(batch):
        acted.append(batch[0])
        return _held_call(gate, entered)()

    verstrs = [f"v{i}" for i in range(2 * MAX_ARCHIVE_BATCH)]
    submitted, _ = runner.submit_bulk("ws", ["exp_archive", APP], lambda: verstrs, act)
    done = _wait(runner, submitted["id"])
    assert done["status"] == "failed" and "Job timed out after 0s" in done["log"]
    assert entered.wait(30)
    gate.set()
    _submit_when_free(runner, "ws", lambda: "ok")
    assert acted == ["v0"]
    assert done["progress"] == {"done": 0, "total": 2 * MAX_ARCHIVE_BATCH}


def test_a_bulk_job_of_many_quick_batches_is_not_timed_out_as_a_whole():
    # Run inline: every batch has returned before its bound is checked, so
    # only a bound on the whole job (0 s, long passed) could fail it.
    runner = JobRunner(timeout_sec=0, processes=RealProcesses(), random=RealRandom(),
                       start_thread=lambda target, *args: target(*args))
    verstrs = [f"v{i}" for i in range(3 * MAX_ARCHIVE_BATCH)]
    submitted, _ = runner.submit_bulk("ws", ["exp_archive", APP], lambda: verstrs, lambda b: "ok")
    done = runner.get(submitted["id"])
    assert done["status"] == "succeeded", done["log"]
    assert done["progress"] == {"done": 3 * MAX_ARCHIVE_BATCH, "total": 3 * MAX_ARCHIVE_BATCH}


def _submit_when_free(runner, workspace, call):
    # The slot has no signal of its own; the bound only fails a real hang.
    deadline = time.time() + HANG_SEC
    while time.time() < deadline:
        job, err = runner.submit_call(workspace, ["note"], call)
        if err is None:
            return job
        time.sleep(0.01)
    raise AssertionError("the workspace slot was never released")


_wait = wait_job
