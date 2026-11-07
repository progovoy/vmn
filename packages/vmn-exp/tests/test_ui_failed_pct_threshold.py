"""Plan 31 §1: ``experiment.ui.failed_pct_threshold`` (default 5), the N of
the Outer runs failed chip's "≥ N% failed" option, rides on the app's
``experiments-status`` like its team views (no field at the default)."""
import pytest
from vmn_exp.core.app_settings import (
    DEFAULT_FAILED_PCT_THRESHOLD,
    failed_pct_threshold_of,
    parse_settings,
)

pytest.importorskip("fastapi")
from test_ui_team_views import _status, store  # noqa: F401


def test_the_threshold_is_the_settings_else_5():
    assert DEFAULT_FAILED_PCT_THRESHOLD == 5
    assert failed_pct_threshold_of(parse_settings("ui: {failed_pct_threshold: 12.5}\n")["ui"]) == 12.5
    assert failed_pct_threshold_of({}) == 5 and failed_pct_threshold_of(None) == 5


def test_the_default_threshold_is_no_field(store):  # noqa: F811
    client_of, _ = store
    assert "failed_pct_threshold" not in _status(client_of()).json()


def test_the_status_carries_the_apps_threshold_and_its_etag_moves(store):  # noqa: F811
    client_of, _ = store
    client = client_of()
    first = _status(client)
    r =client.put("/api/v1/workspaces/ws/apps/app/settings", json={"text": "ui: {failed_pct_threshold: 20}\n"})
    assert r.status_code == 200, r.text
    second = _status(client)
    assert second.json()["failed_pct_threshold"] == 20
    assert second.headers["etag"] != first.headers["etag"]
