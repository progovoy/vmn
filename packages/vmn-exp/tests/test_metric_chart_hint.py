"""Plan 28 N8: the per-metric display hint ``chart`` (``line``/``bars``/
``table``) — declared by ``define_metric``/``vmn-exp add --define-metric
--chart`` or conf/store settings, carried in the effective schema like
``hidden`` and served in run detail's ``metric_charts``."""
import pytest
from exp_helpers import _bootstrap, _exp, _storage

from vmn_exp.core.app_settings import SettingsError, parse_settings
from vmn_exp.core.metric_schema import (
    chart_fields,
    declared_fields,
    declared_schema,
    metric_charts,
)
from vmn_exp.sdk import start_run


def test_chart_fields_accept_only_known_charts():
    assert chart_fields() == {}
    assert chart_fields("bars") == {"chart": "bars"}
    with pytest.raises(ValueError, match="chart"):
        chart_fields("pie")


def test_declared_fields_carry_the_chart():
    defs = {"health.*": {"chart": "bars"}, "lr": {"chart": "pie"}, "x": {"step_metric": "e"}}
    assert declared_fields(defs) == {"health.*": {"chart": "bars"}}
    assert declared_schema([{"m": {"chart": "bars"}}, {"m": {"chart": "table"}}]) == {
        "m": {"chart": "table"}}


def test_metric_charts_from_run_then_schema_exact_beats_glob():
    run_defs = {"health.*": {"chart": "bars"}, "health.ok": {"chart": "line"}}
    schema = {"lr": {"chart": "table"}, "health.*": {"chart": "table"}, "loss": {"goal": "min"}}
    names = ["health.mem", "health.ok", "lr", "loss"]
    assert metric_charts(names, run_defs, schema) == {"health.mem": "bars", "lr": "table"}


def test_settings_validate_the_chart():
    assert parse_settings("metrics: {'nn.*': {chart: bars}}\n")["metrics"] == {
        "nn.*": {"chart": "bars"}}
    with pytest.raises(SettingsError, match="chart"):
        parse_settings("metrics: {loss: {chart: pie}}\n")


def _defs(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return [e for e in log if e.get("type") == "define_metric"]


def test_sdk_define_metric_records_the_chart(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.define_metric("health.*", chart="bars")
        with pytest.raises(ValueError):
            run.define_metric("lr", chart="pie")
        verstr = run.id
    assert [(d["name"], d["chart"]) for d in _defs(app_layout, verstr)] == [("health.*", "bars")]


def _one_run(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.log_metric("loss", 0.5, step=0)
        return run.id


def test_cli_add_define_metric_chart(app_layout):
    verstr = _one_run(app_layout)
    err = _exp(app_layout.app_name, action="add", version=verstr,
               extra_args=["--define-metric", "loss", "--chart", "table"])
    assert err == 0
    [entry] = _defs(app_layout, verstr)
    assert (entry["name"], entry["chart"]) == ("loss", "table")


def test_cli_add_define_metric_rejects_a_bad_chart(app_layout):
    verstr = _one_run(app_layout)
    err = _exp(app_layout.app_name, action="add", version=verstr,
               extra_args=["--define-metric", "loss", "--chart", "pie"])
    assert err != 0
    assert _defs(app_layout, verstr) == []
