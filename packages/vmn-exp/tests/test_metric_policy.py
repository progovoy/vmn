"""Plan 32 F1: a metric's value names its summary policy.

A row's ``metric_policy`` maps each metric whose value the run's own
``define_metric`` summary picked, unlike the schema's (``last`` without one),
to that policy — the override plan 32 decision 1 shows; a value following the
schema is not listed. A min/max/mean summary with no finite value leaves the
metric missing, never its last value (plan 32 rule 3).
"""
import os

import pytest
import yaml
from exp_helpers import _bootstrap, _exp, _storage
from vmn_exp.core.index import indexed_status_rows
from vmn_exp.core.log import experiment_row
from vmn_exp.core.metric_summary import summary_fields
from vmn_exp.core.step_metric import create_define_metric_entry
from vmn_exp.sdk import start_run
from vmn_exp.sdk.reader import list_runs

META = {"verstr": "0.0.1-dev.aaa.bbb", "timestamp": "2026-01-01T00:00:00Z"}
NAN = float("nan")


def _losses(*values):
    return [{"timestamp": f"2026-01-01T00:00:{i:02d}Z", "type": "metrics", "step": i,
             "values": {"loss": v}} for i, v in enumerate(values)]


def _define(summary=None, goal=None):
    return create_define_metric_entry("loss", **summary_fields(summary, goal))


def _row(log, schema=None):
    return experiment_row(1, META, log, schema=schema)


OVERFIT = _losses(1.0, 0.4, 0.9)


def test_a_row_names_the_policy_its_run_defines():
    assert _row([_define("min")] + OVERFIT)["metric_policy"] == {"loss": "min"}
    assert _row([_define("max")] + OVERFIT)["metric_policy"] == {"loss": "max"}


def test_a_value_following_the_schema_is_not_listed():
    assert _row(OVERFIT)["metric_policy"] == {}
    assert _row(OVERFIT, {"loss": {"goal": "min"}})["metric_policy"] == {}
    assert _row([_define("min")] + OVERFIT, {"loss": {"goal": "min"}})["metric_policy"] == {}


def test_a_runs_last_over_a_schema_summary_is_listed():
    log = [_define("last")] + OVERFIT
    assert _row(log, {"loss": {"goal": "min"}})["metric_policy"] == {"loss": "last"}


def test_an_override_is_listed_even_when_it_picks_the_last_value():
    assert _row([_define("min")] + _losses(1.0, 0.2))["metric_policy"] == {"loss": "min"}


def test_a_metric_logged_once_has_no_policy():
    assert _row([_define("min")] + _losses(0.5))["metric_policy"] == {}


@pytest.mark.parametrize("summary", ["min", "max", "mean"])
def test_a_summary_without_a_finite_value_leaves_the_metric_missing(summary):
    row = _row([_define(summary)] + _losses(NAN, NAN))
    assert "loss" not in row["metrics"]
    assert row["metric_policy"] == {}
    assert row["metric_summary"]["loss"][summary] is None


def test_an_empty_schema_summary_leaves_the_metric_missing():
    row = _row(_losses(NAN, float("inf")), {"loss": {"summary": "mean"}})
    assert "loss" not in row["metrics"]


# --- through the index, the reader API, the board and the CLI ---------------


def _run(app_layout, losses, summary=None):
    with start_run(app_layout.app_name) as run:
        if summary:
            run.define_metric("loss", summary=summary)
        for step, loss in enumerate(losses):
            run.log_metric("loss", loss, step=step)
        return run.id


def _seed(app_layout):
    """Two runs logging the same losses, one defining a min summary."""
    _bootstrap(app_layout)
    return _run(app_layout, [1.0, 0.2, 0.9], "min"), _run(app_layout, [1.0, 0.2, 0.9])


def _policies(rows):
    return {r["verstr"]: (r["metrics"].get("loss"), r.get("metric_policy") or {})
            for r in rows}


def test_index_rows_carry_each_runs_policy(app_layout):
    own, plain = _seed(app_layout)
    rows, _, _ = indexed_status_rows(_storage(app_layout), app_layout.app_name, schema={})
    assert _policies(rows) == {own: (0.2, {"loss": "min"}), plain: (0.9, {})}


def test_index_rows_under_a_schema_carry_only_the_overrides(app_layout):
    own, plain = _seed(app_layout)
    schema = {"loss": {"summary": "max"}}
    rows, _, _ = indexed_status_rows(_storage(app_layout), app_layout.app_name, schema=schema)
    assert _policies(rows) == {own: (0.2, {"loss": "min"}), plain: (1.0, {})}


def test_a_row_following_the_schema_carries_no_policy(app_layout):
    _bootstrap(app_layout)
    _run(app_layout, [1.0, 0.2, 0.9])
    rows, _, _ = indexed_status_rows(_storage(app_layout), app_layout.app_name,
                                     schema={"loss": {"goal": "min"}})
    assert rows[0]["metrics"]["loss"] == 0.2 and not rows[0].get("metric_policy")


def test_cli_list_names_the_schemas_policy_too(app_layout, capfd):
    own, plain = _seed(app_layout)
    _write_schema(app_layout, {"loss": {"goal": "min"}})
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list") == 0
    lines = capfd.readouterr().out.splitlines()
    assert "loss=0.2 (min)" in next(line for line in lines if plain in line)


def test_the_reader_api_carries_the_policy(app_layout):
    own, plain = _seed(app_layout)
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout))
    assert _policies(rows) == {own: (0.2, {"loss": "min"}), plain: (0.9, {})}


def _client(app_layout):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def _api(app_layout):
    return f"/api/v1/workspaces/main/apps/{app_layout.app_name}/experiments"


def test_the_board_rows_carry_the_policy(app_layout):
    own, plain = _seed(app_layout)
    rows = _client(app_layout).get(_api(app_layout)).json()
    assert _policies(rows) == {own: (0.2, {"loss": "min"}), plain: (0.9, {})}


def test_the_run_detail_carries_the_policy(app_layout):
    own, plain = _seed(app_layout)
    client = _client(app_layout)
    assert client.get(f"{_api(app_layout)}/{own}").json()["metric_policy"] == {"loss": "min"}
    assert client.get(f"{_api(app_layout)}/{plain}").json()["metric_policy"] == {}


def test_cli_list_names_a_policy_other_than_last(app_layout, capfd):
    own, plain = _seed(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list") == 0
    lines = capfd.readouterr().out.splitlines()
    assert "loss=0.2 (min)" in next(line for line in lines if own in line)
    plain_line = next(line for line in lines if plain in line)
    assert "loss=0.9" in plain_line and "(min)" not in plain_line


def test_cli_show_names_a_policy_other_than_last(app_layout, capfd):
    own, _ = _seed(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="show", version=own) == 0
    line = next(ln for ln in capfd.readouterr().out.splitlines() if ln.strip().startswith("loss:"))
    assert line.split()[:3] == ["loss:", "0.2", "(min)"]


def _write_schema(app_layout, metrics):
    path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    with open(path) as f:
        conf = yaml.safe_load(f) or {}
    conf.setdefault("conf", {}).setdefault("experiment", {})["metrics"] = metrics
    with open(path, "w") as f:
        yaml.dump(conf, f)


def test_cli_show_leaves_a_last_value_unnamed(app_layout, capfd):
    _, plain = _seed(app_layout)
    _write_schema(app_layout, {"loss": {"summary": "last"}})
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="show", version=plain) == 0
    line = next(ln for ln in capfd.readouterr().out.splitlines() if ln.strip().startswith("loss:"))
    assert "(min)" not in line and line.split()[:2] == ["loss:", "0.9"]
