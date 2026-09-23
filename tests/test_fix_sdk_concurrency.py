"""Runs opened concurrently in one process must stay independent.

A thread-pool sweep (Optuna ``n_jobs>1``, a ``ThreadPoolExecutor``) opens one
``start_run()`` per trial. Those trials are siblings: none may become another's
parent through the process-global ``VMN_EXPERIMENT_ID``, and once they have all
finished the environment must be exactly what it was before the first one.
"""
import os
import threading

import pytest
from helpers import _bootstrap, _storage

from version_stamp.core.experiment_status import load_run_state
from version_stamp.exp import run as run_module
from version_stamp.exp import start_run
from version_stamp.exp.run import current_run


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)
    yield
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)


def _parents(app_layout):
    metas = _storage(app_layout).list_snapshots(app_layout.app_name)
    return {m["verstr"]: m.get("parent") for m in metas}


def _run_concurrent_trials(app_layout, n, body=None):
    """Open *n* runs in *n* threads, all open at the same time."""
    all_open = threading.Barrier(n)
    ids, errors = {}, []

    def trial(i):
        try:
            with start_run(app_layout.app_name, note=f"trial {i}") as run:
                ids[i] = run.id
                all_open.wait(timeout=60)
                if body:
                    body(i, run)
                all_open.wait(timeout=60)
        except Exception as exc:  # surfaced below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=trial, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    return ids


def test_threaded_trials_are_independent_siblings(app_layout):
    _bootstrap(app_layout)

    ids = _run_concurrent_trials(app_layout, 4)

    parents = _parents(app_layout)
    assert sorted(parents) == sorted(ids.values())
    assert all(p is None for p in parents.values()), parents


def test_env_is_restored_after_threaded_runs_finish(app_layout):
    _bootstrap(app_layout)

    _run_concurrent_trials(app_layout, 4)

    assert "VMN_EXPERIMENT_ID" not in os.environ
    assert "VMN_APP_NAME" not in os.environ


def test_env_baseline_survives_threaded_runs(app_layout):
    _bootstrap(app_layout)
    os.environ["VMN_EXPERIMENT_ID"] = "launcher-value"

    _run_concurrent_trials(app_layout, 3)

    assert os.environ["VMN_EXPERIMENT_ID"] == "launcher-value"


def test_current_run_is_the_threads_own_run(app_layout):
    _bootstrap(app_layout)
    seen = {}

    ids = _run_concurrent_trials(
        app_layout, 3, body=lambda i, run: seen.__setitem__(i, current_run())
    )

    assert {i: r.id for i, r in seen.items()} == ids


def test_current_run_falls_back_to_the_sole_open_run(app_layout):
    _bootstrap(app_layout)
    seen = []

    with start_run(app_layout.app_name) as run:
        t = threading.Thread(target=lambda: seen.append(current_run()))
        t.start()
        t.join()

    assert seen == [run]


def test_current_run_is_none_when_ambiguous(app_layout):
    _bootstrap(app_layout)
    seen = []

    def body(i, run):
        if i == 0:
            t = threading.Thread(target=lambda: seen.append(current_run()))
            t.start()
            t.join()

    _run_concurrent_trials(app_layout, 2, body=body)

    assert seen == [None]


def test_current_run_is_none_once_finished(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as run:
        assert current_run() is run
        assert run.pid == os.getpid()

    assert current_run() is None


def test_nested_uses_the_context_run_not_the_last_opened(app_layout):
    _bootstrap(app_layout)
    outer_open = threading.Event()
    other_open = threading.Event()
    done = threading.Event()
    result = {}

    def owner():
        with start_run(app_layout.app_name, note="outer") as outer:
            result["outer"] = outer.id
            outer_open.set()
            other_open.wait(timeout=60)
            with start_run(app_layout.app_name, nested=True) as inner:
                result["inner"] = inner.id
        done.set()

    def other():
        outer_open.wait(timeout=60)
        with start_run(app_layout.app_name, note="other") as run:
            result["other"] = run.id
            other_open.set()
            done.wait(timeout=60)

    threads = [threading.Thread(target=owner), threading.Thread(target=other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    parents = _parents(app_layout)
    assert parents[result["inner"]] == result["outer"]
    assert parents[result["other"]] is None


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_forked_child_inherits_no_open_run(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as run:
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # child
            try:
                # atexit would run this in a child that exits normally: it must
                # not finalize (and so mark failed) the parent's still-open run.
                run_module._finalize_open_runs()
                verdict = "ok" if current_run() is None else "leaked"
            except Exception as exc:  # pragma: no cover - reported to parent
                verdict = f"error {exc!r}"
            os.write(write_fd, verdict.encode())
            os._exit(0)
        os.close(write_fd)
        _, status = os.waitpid(pid, 0)
        verdict = os.read(read_fd, 1000).decode()
        os.close(read_fd)
        assert verdict == "ok"
        state = load_run_state(_storage(app_layout), app_layout.app_name, run.id)
        assert state["state"] == "running" and state["exit_code"] is None
        assert current_run() is run


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_run_started_in_a_forked_child_is_an_inner_run(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, note="parent") as outer:
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # child
            try:
                with start_run(app_layout.app_name, note="child") as inner:
                    pass
                verdict = inner.id
            except Exception as exc:  # pragma: no cover - reported to parent
                verdict = f"error {exc!r}"
            os.write(write_fd, verdict.encode())
            os._exit(0)
        os.close(write_fd)
        os.waitpid(pid, 0)
        child_id = os.read(read_fd, 1000).decode()
        os.close(read_fd)

    assert not child_id.startswith("error"), child_id
    assert _parents(app_layout)[child_id] == outer.id
