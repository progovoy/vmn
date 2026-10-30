"""``create_run``: register a run in the waiting state from the SDK.

A launcher registers every pod up front, so the outer run's totals are right
before any pod starts; each pod then takes its run with ``start_run(run_id=)``.
"""
import os

import pytest
from exp_helpers import _bootstrap, _storage

from vmn_exp.sdk import create_run, current_run, start_run
from vmn_exp.sdk.reader import list_runs


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    keys = ("VMN_EXPERIMENT_ID", "VMN_APP_NAME")
    for key in keys:
        os.environ.pop(key, None)
    yield
    for key in keys:
        os.environ.pop(key, None)


def _row(app_layout, verstr):
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout), use_index=False)
    return next(r for r in rows if r["verstr"] == verstr)


def test_create_run_registers_a_waiting_run(app_layout):
    _bootstrap(app_layout)

    verstr = create_run(app_layout.app_name, name="pod0", params={"shard": 0})

    row = _row(app_layout, verstr)
    assert row["status"] == "created"
    assert row["name"] == "pod0"
    assert row["params"]["shard"] == 0
    assert current_run() is None


def test_registered_pods_count_as_waiting_children_of_the_outer(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, name="outer") as outer:
        pods = [create_run(app_layout.app_name, name=f"pod{i}") for i in range(3)]
        assert current_run() is outer

    for verstr in pods:
        row = _row(app_layout, verstr)
        assert row["parent"] == outer.id
        assert row["status"] == "created"


def test_explicit_parent_from_another_process(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, name="outer") as outer:
        pass

    verstr = create_run(app_layout.app_name, parent=outer.id)

    assert _row(app_layout, verstr)["parent"] == outer.id


def test_a_pod_takes_its_registered_run(app_layout):
    _bootstrap(app_layout)
    verstr = create_run(app_layout.app_name, name="pod0")

    with start_run(app_layout.app_name, run_id=verstr) as pod:
        assert pod.id == verstr
        assert _row(app_layout, verstr)["status"] == "running"
        pod.log_metric("loss", 0.5)

    row = _row(app_layout, verstr)
    assert row["status"] == "succeeded"
    assert row["metrics"]["loss"] == 0.5


def test_a_retried_pod_reopens_its_failed_run(app_layout):
    # One trial run, several pod attempts: a crash records failed, a retry
    # reopens the same run and its success is the run's final status.
    _bootstrap(app_layout)
    verstr = create_run(app_layout.app_name, name="trial0")

    first = start_run(app_layout.app_name, run_id=verstr, tags={"attempt": "1"})
    first.finish(exit_code=1)
    assert _row(app_layout, verstr)["status"] == "failed"

    with start_run(app_layout.app_name, run_id=verstr, tags={"attempt": "2"},
                   reopen=True):
        assert _row(app_layout, verstr)["status"] == "running"

    row = _row(app_layout, verstr)
    assert row["status"] == "succeeded"
    assert row["tags"]["attempt"] == "2"


def test_create_run_with_run_id_names_the_checkout_run_exactly(app_layout):
    _bootstrap(app_layout)
    code = _storage(app_layout).load_metadata(
        app_layout.app_name, create_run(app_layout.app_name))["code_verstr"]

    verstr = create_run(app_layout.app_name, run_id=f"{code}.job-1", name="pod0")

    assert verstr == f"{code}.job-1"
    assert _row(app_layout, verstr)["name"] == "pod0"
