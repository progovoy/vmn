"""``run.define_metric()`` and the CLI views of best-value summaries.

A run's own definition travels with its log (a ``define_metric`` entry), so
every reader — ``list_runs``, the query language, ``vmn-exp list --sort``,
``prune --query`` — ranks it on its best value without any conf.yml.
"""
import os

import pytest
import yaml
from helpers import _bootstrap, _exp, _storage

from vmn_exp.sdk import start_run
from vmn_exp.sdk.ranks import NoOpRun
from vmn_exp.sdk.reader import list_runs


def _run(app_layout, losses, define=None):
    with start_run(app_layout.app_name) as run:
        if define:
            run.define_metric("loss", **define)
        for step, loss in enumerate(losses):
            run.log_metric("loss", loss, step=step)
        return run.id


def _seed(app_layout, define=None):
    """An overfitting run (best 0.2, last 0.9) and a steady one (0.5)."""
    _bootstrap(app_layout)
    overfit = _run(app_layout, [1.0, 0.2, 0.9], define)
    steady = _run(app_layout, [0.8, 0.5], define)
    return overfit, steady


def _write_goal_min(app_layout):
    path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    with open(path) as f:
        conf = yaml.safe_load(f) or {}
    conf.setdefault("conf", {}).setdefault("experiment", {})["metrics"] = {
        "loss": {"goal": "min"}
    }
    with open(path, "w") as f:
        yaml.dump(conf, f)


def _rows(app_layout, **kwargs):
    return list_runs(app_layout.app_name, storage=_storage(app_layout), **kwargs)


def test_define_metric_is_recorded_in_the_log(app_layout):
    overfit, _ = _seed(app_layout, {"summary": "min"})
    log = _storage(app_layout).load_merged_log(app_layout.app_name, overfit)
    defs = [e for e in log if e.get("type") == "define_metric"]
    assert [(d["name"], d["summary"]) for d in defs] == [("loss", "min")]


def test_define_metric_is_honoured_without_any_conf(app_layout):
    overfit, steady = _seed(app_layout, {"summary": "min"})
    rows = _rows(app_layout)
    assert {r["verstr"]: r["metrics"]["loss"] for r in rows} == {overfit: 0.2, steady: 0.5}
    assert [r["verstr"] for r in _rows(app_layout, query="metrics.loss < 0.3")] == [overfit]
    assert [r["verstr"] for r in _rows(app_layout, sort="loss")] == [overfit, steady]


def test_define_metric_goal_derives_the_summary(app_layout):
    overfit, _ = _seed(app_layout, {"goal": "min"})
    assert next(r for r in _rows(app_layout) if r["verstr"] == overfit)["metrics"][
        "loss"
    ] == 0.2


def test_define_metric_rejects_an_unknown_summary(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        with pytest.raises(ValueError):
            run.define_metric("loss", summary="median")


def test_a_no_op_run_accepts_define_metric():
    assert NoOpRun().define_metric("loss", summary="min") is None


def test_cli_list_sorts_on_the_best_value(app_layout, capfd):
    overfit, steady = _seed(app_layout)
    _write_goal_min(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list", sort="loss") == 0
    out = capfd.readouterr().out
    assert out.index(overfit) < out.index(steady), out


def test_cli_show_prints_last_min_and_max(app_layout, capfd):
    overfit, _ = _seed(app_layout)
    _write_goal_min(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="show", version=overfit) == 0
    line = next(l for l in capfd.readouterr().out.splitlines()
                if l.strip().startswith("loss:"))
    assert line.split() == ["loss:", "0.2", "(last", "0.9,", "min", "0.2,", "max", "1)"]


def test_cli_compare_shows_the_best_value(app_layout, capfd):
    overfit, steady = _seed(app_layout)
    _write_goal_min(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="compare", version=[overfit, steady]) == 0
    line = next(l for l in capfd.readouterr().out.splitlines() if l.startswith("loss"))
    assert line.split()[1:3] == ["0.2", "0.5"], line


def test_prune_query_selects_on_the_best_value(app_layout, capfd):
    overfit, steady = _seed(app_layout)
    _write_goal_min(app_layout)
    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune",
               extra_args=["--query", "metrics.loss < 0.3"])
    out = capfd.readouterr().out
    assert err == 0
    assert overfit in out and steady not in out, out


def test_one_define_metric_call_sets_summary_and_step_metric(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.define_metric("loss", step_metric="epoch", summary="min")
        for step, loss in enumerate([1.0, 0.2, 0.9]):
            run.log_metrics({"loss": loss, "epoch": step}, step=step)
        verstr = run.id
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    defs = [e for e in log if e.get("type") == "define_metric"]
    assert [(d["summary"], d["step_metric"]) for d in defs] == [("min", "epoch")]
    assert _rows(app_layout)[0]["metrics"]["loss"] == 0.2


def test_define_metric_rejects_an_unknown_goal(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        with pytest.raises(ValueError):
            run.define_metric("loss", goal="up")
