"""``GET .../experiments/{verstr}/sweep`` — a sweep's attributed trials, as
``vmn-exp sweep status`` sees them (a trial's metric may come from the run a
``start_run()`` inside it nested under it)."""
import os

import pytest

from test_sweep_cli import _status, _trials, _vmn_exp
from test_sweep_sdk_trials import _sdk_sweep

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

API = "/api/v1/workspaces/main/apps"


@pytest.fixture(autouse=True)
def _sdk_child_env(monkeypatch):
    from helpers import _SRC_PATH

    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SWEEP_PARAMS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PYTHONPATH", _SRC_PATH)


@pytest.fixture
def swept(app_layout, tmp_path, capsys):
    """A finished 3-trial grid sweep whose trials log through the SDK."""
    sweep = _sdk_sweep(app_layout, tmp_path, capsys)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    return sweep


def _client(app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def _url(app_layout, verstr):
    return f"{API}/{app_layout.app_name}/experiments/{verstr}/sweep"


def test_sweep_endpoint_serves_the_attributed_trials(app_layout, swept, capsys):
    resp = _client(app_layout).get(_url(app_layout, swept))
    assert resp.status_code == 200
    body = resp.json()
    assert body["sweep"] == swept
    assert body["spec"]["metric"] == {"name": "loss", "goal": "min"}

    trials = _trials(app_layout, swept)
    assert [t["verstr"] for t in body["trials"]] == [t["verstr"] for t in trials]
    first = body["trials"][0]
    assert first["trial"] == 0 and first["attempt"] == 0
    assert first["status"] == "succeeded"
    assert first["params"] == {"x": 3}
    assert first["value"] == pytest.approx(3.25)
    assert first["metric_source"] != first["verstr"]  # the nested SDK run
    assert first["stopped_early"] is False

    # The same answer as the CLI's status.
    status = _status(app_layout, swept, capsys)
    assert body["summary"]["best"] == status["best"]
    assert body["summary"]["counts"] == {"succeeded": 3}


def test_sweep_endpoint_answers_304_for_an_unchanged_etag(app_layout, swept):
    client = _client(app_layout)
    first = client.get(_url(app_layout, swept))
    etag = first.headers["etag"]
    again = client.get(_url(app_layout, swept), headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_a_run_that_is_not_a_sweep_is_404(app_layout, swept):
    client = _client(app_layout)
    trial = _trials(app_layout, swept)[0]["verstr"]
    assert client.get(_url(app_layout, trial)).status_code == 404
    assert client.get(_url(app_layout, "0.0.9-nope")).status_code == 404


def test_an_unsafe_verstr_is_400(app_layout):
    resp = _client(app_layout).get(_url(app_layout, "a%5Cb"))
    assert resp.status_code == 400
    assert "Invalid version" in resp.json()["detail"]
