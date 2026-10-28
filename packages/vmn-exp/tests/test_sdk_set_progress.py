"""Plan 28 P2: ``run.set_progress(done, total, unit)`` logs the declared
progress an outer run's bar reads: ``progress``/``progress_total`` step-less,
the unit as the ``progress_unit`` param."""
import pytest
from exp_helpers import _bootstrap, _storage
from vmn_exp.sdk import start_run
from vmn_exp.sdk.ranks import NoOpRun


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID", "VMN_MODE"):
        monkeypatch.delenv(key, raising=False)


def _entries(app_layout, verstr, kind):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return [e for e in log if e.get("type") == kind]


def test_set_progress_logs_both_metrics_without_a_step_and_the_unit_once(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, system_metrics=False) as run:
        run.set_progress(1, 60, unit="dates")
        run.set_progress(2, 60, unit="dates")
        assert run.step == 0
    metrics = _entries(app_layout, run.id, "metrics")
    assert [e["values"] for e in metrics] == [{"progress": 1, "progress_total": 60},
                                              {"progress": 2, "progress_total": 60}]
    assert all("step" not in e for e in metrics)
    units = [e["params"] for e in _entries(app_layout, run.id, "params")]
    assert units == [{"progress_unit": "dates"}]


def test_without_a_total_only_progress_is_logged(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, system_metrics=False) as run:
        run.set_progress(3)
    assert [e["values"] for e in _entries(app_layout, run.id, "metrics")] == [{"progress": 3}]
    assert _entries(app_layout, run.id, "params") == []


def test_the_folded_row_carries_the_last_progress(app_layout):
    from vmn_exp.sdk.reader import get_run

    _bootstrap(app_layout)
    with start_run(app_layout.app_name, system_metrics=False) as run:
        run.set_progress(1, 60)
        run.set_progress(41, 60, unit="dates")
    row = get_run(app_layout.app_name, run.id, storage=_storage(app_layout))
    assert (row["metrics"]["progress"], row["metrics"]["progress_total"]) == (41, 60)
    assert row["params"]["progress_unit"] == "dates"


def test_a_noop_run_takes_set_progress_and_records_nothing():
    run = NoOpRun("app")
    assert run.set_progress(1, 2, unit="dates") is None
    assert run.step == 0
