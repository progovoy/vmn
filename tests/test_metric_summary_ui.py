"""The ui leaderboard and run detail rank on best-value metric summaries."""
import os

import pytest
import yaml
from helpers import _bootstrap

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.sdk import start_run  # noqa: E402


def _run(app_layout, losses):
    with start_run(app_layout.app_name) as run:
        for step, loss in enumerate(losses):
            run.log_metric("loss", loss, step=step)
        return run.id


def _set_metrics(app_layout, metrics):
    path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    with open(path) as f:
        conf = yaml.safe_load(f) or {}
    conf.setdefault("conf", {}).setdefault("experiment", {})["metrics"] = metrics
    with open(path, "w") as f:
        yaml.dump(conf, f)


def _client(app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def _seed(app_layout):
    _bootstrap(app_layout)
    overfit = _run(app_layout, [1.0, 0.2, 0.9])
    steady = _run(app_layout, [0.8, 0.5])
    _set_metrics(app_layout, {"loss": {"goal": "min"}})
    return overfit, steady


def _api(app_layout):
    return f"/api/v1/workspaces/main/apps/{app_layout.app_name}/experiments"


def test_leaderboard_ranks_on_the_best_value(app_layout):
    overfit, steady = _seed(app_layout)
    rows = _client(app_layout).get(_api(app_layout), params={"sort": "loss"}).json()
    assert [r["verstr"] for r in rows] == [overfit, steady]
    assert rows[0]["metrics"]["loss"] == 0.2


def test_leaderboard_follows_a_conf_change(app_layout):
    overfit, steady = _seed(app_layout)
    client = _client(app_layout)
    client.get(_api(app_layout), params={"sort": "loss"})
    _set_metrics(app_layout, {"loss": {"goal": "min", "summary": "last"}})
    rows = client.get(_api(app_layout), params={"sort": "loss"}).json()
    assert [r["verstr"] for r in rows] == [steady, overfit]
    assert rows[1]["metrics"]["loss"] == 0.9


def test_detail_carries_best_and_last(app_layout):
    overfit, _ = _seed(app_layout)
    detail = _client(app_layout).get(f"{_api(app_layout)}/{overfit}").json()
    assert detail["metrics"]["loss"] == 0.2
    assert detail["metric_summary"]["loss"] == {
        "last": 0.9, "min": 0.2, "max": 1.0, "first": 1.0, "mean": pytest.approx(0.7)}
