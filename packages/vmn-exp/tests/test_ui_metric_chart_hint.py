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


def _epochs_run(app_layout, epochs=10, members=64):
    """A per-member metric logged at steps 0..members-1 every epoch: the
    last epoch's value at step s is ``1000 + s``."""
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.define_metric("health.m", chart="bars")
        for epoch in range(epochs):
            last = epoch == epochs - 1
            for step in range(members):
                value = 1000 + step if last else (step * 7919 + epoch * 104729) % 997
                run.log_metric("health.m", float(value), step=step)
        run.log_metric("loss", 0.5, step=0)
        return run.id


def test_detail_serves_the_unthinned_last_value_per_step(app_layout):
    verstr = _epochs_run(app_layout)
    detail = _client(app_layout).get(
        f"{_base(app_layout)}/experiments/{verstr}", params={"max_points": 50}).json()
    assert detail["series_total"]["health.m"] == 640
    assert len(detail["series"]["health.m"]) <= 50  # thinned
    steps = detail["metric_steps"]["health.m"]
    assert steps["total"] == 64
    assert steps["rows"] == [{"step": s, "value": 1000.0 + s} for s in range(64)]
    assert "loss" not in detail["metric_steps"]


def test_metric_steps_keep_the_latest_steps_past_the_cap(app_layout, monkeypatch):
    from vmn_exp.ui.readers import log_snapshot

    monkeypatch.setattr(log_snapshot, "MAX_HINTED_STEPS", 10)
    verstr = _epochs_run(app_layout, epochs=1, members=30)
    detail = _client(app_layout).get(f"{_base(app_layout)}/experiments/{verstr}").json()
    steps = detail["metric_steps"]["health.m"]
    assert steps["total"] == 30
    assert [r["step"] for r in steps["rows"]] == list(range(20, 30))
