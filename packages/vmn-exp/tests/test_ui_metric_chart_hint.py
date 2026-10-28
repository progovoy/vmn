"""Plan 28 N8: the ui serves the ``chart`` display hint where it serves
``hidden``: run detail's ``metric_charts`` and ``/metrics-schema``."""
import pytest
from exp_helpers import _bootstrap

pytest.importorskip("fastapi")

from test_ui_metric_schema import (  # noqa: E402
    APP,
    _base,
    _client,
    _set_metrics,
    _store_run,
)
from test_ui_metric_schema import s3_client  # noqa: E402,F401  (fixture)

from vmn_exp.sdk import start_run  # noqa: E402


def test_detail_lists_metric_charts_from_run_and_conf(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.define_metric("health.*", chart="bars")
        run.log_metrics({"health.mem": 1.0, "lr": 0.1, "loss": 0.5}, step=0)
        verstr = run.id
    _set_metrics(app_layout, {"lr": {"chart": "table"}})
    detail = _client(app_layout).get(f"{_base(app_layout)}/experiments/{verstr}").json()
    assert detail["metric_charts"] == {"health.mem": "bars", "lr": "table"}


def test_metrics_schema_endpoint_carries_a_declared_chart(s3_client):  # noqa: F811
    client, storage = s3_client
    _store_run(storage, "1.0.0-dev.a", 1, [
        {"type": "define_metric", "name": "nn.*", "chart": "bars"},
        {"type": "metrics", "values": {"nn.g": 0.9}}])
    schema = client.get(f"/api/v1/workspaces/ws/apps/{APP}/metrics-schema").json()
    assert schema == {"nn.*": {"chart": "bars"}}
