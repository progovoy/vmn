"""``define_metric(hidden=...)`` and ``vmn-exp add --define-metric``."""
import pytest
from helpers import _bootstrap, _exp, _storage

from vmn_exp.sdk import start_run


def _defs(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return [e for e in log if e.get("type") == "define_metric"]


def _one_run(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.log_metric("loss", 0.5, step=0)
        return run.id


def test_define_metric_hidden_is_recorded(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.define_metric("grad_*", hidden=True)
        verstr = run.id
    assert [(d["name"], d["hidden"]) for d in _defs(app_layout, verstr)] == [
        ("grad_*", True)]


def test_hidden_must_be_bool(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        with pytest.raises(ValueError):
            run.define_metric("grad_norm", hidden="yes")


def test_cli_add_define_metric_appends_entry(app_layout):
    verstr = _one_run(app_layout)
    err = _exp(app_layout.app_name, action="add", version=verstr, extra_args=[
        "--define-metric", "loss", "--goal", "min", "--summary", "mean",
        "--step-metric", "epoch", "--hidden"])
    assert err == 0
    [entry] = _defs(app_layout, verstr)
    assert {k: entry[k] for k in ("name", "goal", "summary", "step_metric", "hidden")} == {
        "name": "loss", "goal": "min", "summary": "mean", "step_metric": "epoch",
        "hidden": True}


def test_cli_add_define_metric_without_options_is_refused(app_layout):
    verstr = _one_run(app_layout)
    err = _exp(app_layout.app_name, action="add", version=verstr,
               extra_args=["--define-metric", "loss"])
    assert err != 0
    assert _defs(app_layout, verstr) == []


def test_cli_add_define_metric_rejects_bad_summary(app_layout):
    verstr = _one_run(app_layout)
    err = _exp(app_layout.app_name, action="add", version=verstr,
               extra_args=["--define-metric", "loss", "--summary", "median"])
    assert err != 0
    assert _defs(app_layout, verstr) == []
