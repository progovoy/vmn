"""``start_run(export_env=False)``: the run is registered in-process (current
run, heartbeat, atexit) but never touches ``VMN_EXPERIMENT_ID`` /
``VMN_APP_NAME`` — an orchestrator opening several runs from worker threads
keeps the process-shared env out of their parent picks."""
import os
import threading

import pytest
from exp_helpers import _bootstrap, _storage

from vmn_exp.sdk import start_run
from vmn_exp.sdk.run import current_run

ENV_KEYS = ("VMN_EXPERIMENT_ID", "VMN_APP_NAME")


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    yield
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _env():
    return {key: os.environ.get(key) for key in ENV_KEYS}


def _parents(app_layout):
    metas = _storage(app_layout).list_snapshots(app_layout.app_name)
    return {m["verstr"]: m.get("parent") for m in metas}


def test_unexported_run_leaves_the_env_alone(app_layout):
    _bootstrap(app_layout)
    os.environ["VMN_EXPERIMENT_ID"] = "launcher-value"

    with start_run(app_layout.app_name, export_env=False) as run:
        assert current_run() is run
        assert _env() == {"VMN_EXPERIMENT_ID": "launcher-value", "VMN_APP_NAME": None}

    assert _env() == {"VMN_EXPERIMENT_ID": "launcher-value", "VMN_APP_NAME": None}


def test_unexported_run_closing_does_not_reexport_an_open_run(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as outer:
        with start_run(app_layout.app_name, nested=True, export_env=False) as inner:
            assert os.environ["VMN_EXPERIMENT_ID"] == outer.id
        assert os.environ["VMN_EXPERIMENT_ID"] == outer.id

    assert _parents(app_layout)[inner.id] == outer.id
    assert _env() == {"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}


def test_exported_run_closing_does_not_export_an_unexported_one(app_layout):
    _bootstrap(app_layout)

    exported = start_run(app_layout.app_name)
    with start_run(app_layout.app_name, nested=True, export_env=False):
        exported.finish()
        assert _env() == {"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}

    assert _env() == {"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}


def test_threaded_unexported_runs_never_set_the_env(app_layout):
    _bootstrap(app_layout)
    all_open = threading.Barrier(3)
    seen, ids, errors = [], {}, []

    def trial(i):
        try:
            with start_run(app_layout.app_name, export_env=False) as run:
                ids[i] = run.id
                all_open.wait(timeout=60)
                seen.append(_env())
                all_open.wait(timeout=60)
        except Exception as exc:  # surfaced below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=trial, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert seen == [{"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}] * 3
    assert all(p is None for p in _parents(app_layout).values())


def test_reopened_unexported_run_leaves_the_env_alone(app_layout):
    _bootstrap(app_layout)
    first = start_run(app_layout.app_name, export_env=False)
    first.release()

    with start_run(app_layout.app_name, run_id=first.id, export_env=False) as run:
        assert run.id == first.id and current_run() is run
        assert _env() == {"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}


def test_unexported_study_keeps_threaded_trials_out_of_the_env(app_layout):
    optuna = pytest.importorskip("optuna")
    from vmn_exp.integrations.optuna_study import start_study_run

    _bootstrap(app_layout)
    seen = []

    def objective(trial):
        seen.append(_env())
        return trial.suggest_float("x", -1.0, 1.0) ** 2

    study = optuna.create_study()
    tracker = start_study_run(study, app_name=app_layout.app_name, export_env=False)
    seen.append(_env())
    study.optimize(tracker.wrap(objective), n_trials=3, n_jobs=3)
    tracker.finish()

    assert seen == [{"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}] * 4
    parents = _parents(app_layout)
    assert sorted(p for p in parents.values() if p) == [tracker._outer_id] * 3


def test_attached_unexported_study_leaves_the_env_alone(app_layout):
    optuna = pytest.importorskip("optuna")
    from vmn_exp.integrations.optuna_study import start_study_run

    _bootstrap(app_layout)
    outer = start_run(app_layout.app_name, export_env=False)
    outer.finish()
    seen = []

    study = optuna.create_study()
    tracker = start_study_run(
        study, app_name=app_layout.app_name, outer=outer.id, export_env=False)
    study.optimize(tracker.wrap(lambda t: seen.append(_env()) or 0.0), n_trials=1)
    tracker.finish()

    assert seen == [{"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}]
    assert _env() == {"VMN_EXPERIMENT_ID": None, "VMN_APP_NAME": None}
