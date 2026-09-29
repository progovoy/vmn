"""Forking a run (``start_run(fork_from=..., fork_step=N)``) and rewinding one
(``start_run(run_id=..., rewind_to_step=N)``).

A fork is a NEW run that starts with its source's history up to step N; a
rewind reopens the SAME run and hides its history after step N.
"""
import datetime

import pytest
import yaml
from helpers import _bootstrap, _exp, _storage

from vmn_exp.core.log import latest_metrics, metric_series
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.sdk import start_run
from vmn_exp.sdk.reader import list_runs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def _meta(app_layout, verstr):
    return _storage(app_layout).load(app_layout.app_name, verstr)[0]


def _steps(log):
    return [(p["step"], p["value"]) for p in metric_series(log)["loss"]]


def _source(app_layout, steps=4):
    with start_run(app_layout.app_name, params={"lr": 0.1}) as run:
        for step in range(1, steps + 1):
            run.log_metric("loss", 1.0 / step, step=step)
    return run.id


# -- fork ---------------------------------------------------------------------


def test_a_fork_copies_the_history_up_to_the_step_and_continues(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)

    with start_run(app_layout.app_name, fork_from=source, fork_step=2) as fork:
        assert fork.id != source
        assert fork.start_step == 3
        fork.log_metric("loss", 0.01, step=3)

    assert _meta(app_layout, fork.id)["forked_from"] == {"verstr": source, "step": 2}
    log = _log(app_layout, fork.id)
    assert _steps(log) == [(1, 1.0), (2, 0.5), (3, 0.01)]
    inherited = [e for e in log if e.get("inherited")]
    assert {e["type"] for e in inherited} == {"metrics", "params"}
    assert all(e.get("step", 0) <= 2 for e in inherited)
    assert latest_metrics(log)["loss"] == 0.01
    assert _steps(_log(app_layout, source))[-1] == (4, 0.25)  # source untouched


def test_the_fork_step_can_ride_on_the_ref(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)

    with start_run(app_layout.app_name, fork_from=f"{source}?_step=1") as fork:
        pass
    assert _meta(app_layout, fork.id)["forked_from"] == {"verstr": source, "step": 1}
    assert _steps(_log(app_layout, fork.id)) == [(1, 1.0)]


def test_a_fork_without_a_step_copies_everything(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout, steps=3)

    with start_run(app_layout.app_name, fork_from=source) as fork:
        assert fork.start_step == 4
    assert _meta(app_layout, fork.id)["forked_from"] == {"verstr": source, "step": 3}
    assert len(_steps(_log(app_layout, fork.id))) == 3


def test_a_forks_own_params_win_over_inherited_ones(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)

    with start_run(app_layout.app_name, fork_from=source, fork_step=1,
                   params={"lr": 0.5}) as fork:
        pass
    row = next(r for r in list_runs(app_layout.app_name) if r["verstr"] == fork.id)
    assert row["params"]["lr"] == 0.5


def test_a_fork_is_not_a_child(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)
    with start_run(app_layout.app_name, fork_from=source, fork_step=1) as fork:
        pass

    rows = {r["verstr"]: r for r in list_runs(app_layout.app_name)}
    assert rows[fork.id]["forked_from"] == source
    assert rows[fork.id]["forked_from_step"] == 1
    assert rows[fork.id]["parent"] is None
    assert rows[fork.id]["kind"] == "single"
    assert rows[source]["kind"] == "single"
    assert rows[source]["forked_from"] is None


def test_forks_are_queryable(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)
    with start_run(app_layout.app_name, fork_from=source, fork_step=1) as fork:
        pass

    found = list_runs(app_layout.app_name, query=f'forked_from = "{source}"')
    assert [r["verstr"] for r in found] == [fork.id]


def test_forking_an_unknown_run_creates_nothing(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)

    with pytest.raises(ValueError, match="no-such-run"):
        start_run(app_layout.app_name, fork_from="no-such-run")
    verstrs = [m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)]
    assert verstrs == [source]


def test_fork_and_resume_do_not_mix(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)
    with pytest.raises(ValueError, match="fork_from"):
        start_run(app_layout.app_name, run_id=source, fork_from=source)


# -- rewind -------------------------------------------------------------------


def test_rewind_hides_later_history_and_logging_continues(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)

    with start_run(app_layout.app_name, run_id=source, rewind_to_step=2) as run:
        assert run.id == source
        assert run.start_step == 3
        run.log_metric("loss", 0.9, step=3)

    log = _log(app_layout, source)
    assert _steps(log) == [(1, 1.0), (2, 0.5), (3, 0.9)]
    assert latest_metrics(log)["loss"] == 0.9
    row = list_runs(app_layout.app_name)[0]
    assert row["metrics"]["loss"] == 0.9


def test_rewind_needs_a_run_to_resume(app_layout):
    _bootstrap(app_layout)
    with pytest.raises(ValueError, match="rewind_to_step"):
        start_run(app_layout.app_name, rewind_to_step=1)


def test_rewinding_a_run_that_is_running_elsewhere_is_refused(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)
    storage = _storage(app_layout)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    state = dict(load_run_state(storage, app_layout.app_name, source))
    state.update(state="running", exit_code=None, finished_at=None, heartbeat=now,
                 host="elsewhere", pid=1)
    storage.save_file(app_layout.app_name, source, RUN_STATE_FILE, yaml.safe_dump(state))

    with pytest.raises(RuntimeError, match="running"):
        start_run(app_layout.app_name, run_id=source, rewind_to_step=1)
    assert _steps(_log(app_layout, source))[-1] == (4, 0.25)


# -- CLI ----------------------------------------------------------------------


def test_cli_create_forks_a_run(app_layout, capfd):
    _bootstrap(app_layout)
    source = _source(app_layout)
    capfd.readouterr()

    assert _exp(app_layout.app_name, extra_args=["--fork-from", source,
                                                "--fork-step", "2"]) == 0
    fork = capfd.readouterr().out.strip().splitlines()[-1]
    assert _meta(app_layout, fork)["forked_from"] == {"verstr": source, "step": 2}
    assert _steps(_log(app_layout, fork)) == [(1, 1.0), (2, 0.5)]

    assert _exp(app_layout.app_name, action="show", version=fork) == 0
    out = capfd.readouterr().out
    assert f"Forked from: {source} @ step 2" in out


def test_cli_run_forks_a_run(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)

    assert _exp(app_layout.app_name, action="run",
                extra_args=["--fork-from", source, "--fork-step", "1"],
                run_cmd=["true"]) == 0
    forks = [m for m in _storage(app_layout).list_snapshots(app_layout.app_name)
             if m.get("forked_from")]
    assert [m["forked_from"] for m in forks] == [{"verstr": source, "step": 1}]


def test_cli_show_lists_rewinds(app_layout, capfd):
    _bootstrap(app_layout)
    source = _source(app_layout)
    with start_run(app_layout.app_name, run_id=source, rewind_to_step=2):
        pass
    capfd.readouterr()

    assert _exp(app_layout.app_name, action="show", version=source) == 0
    assert "Rewound to step 2" in capfd.readouterr().out
