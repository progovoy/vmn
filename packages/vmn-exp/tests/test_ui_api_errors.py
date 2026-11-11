"""api_errors.install answers a ValueError raised under a request with 400
and its message, and logs it at warning with the method, path and stack so
an operator sees server bugs the 400 relabels as client errors."""
import logging

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.files import safe_verstr  # noqa: E402
from vmn_exp.ui import api_errors  # noqa: E402


def _client():
    app = FastAPI()
    api_errors.install(app)

    @app.get("/boom")
    def _boom():
        int("x")

    @app.get("/runs")
    def _run(verstr: str):
        return {"name": safe_verstr(verstr)}

    return TestClient(app)


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


def test_value_error_is_400_and_logged_with_stack(caplog):
    caplog.set_level(logging.WARNING)

    response = _client().get("/boom?q=1")

    assert response.status_code == 400
    assert response.json() == {
        "detail": "invalid literal for int() with base 10: 'x'"
    }
    (record,) = _warnings(caplog)
    assert record.name.startswith("vmn_exp.ui")
    assert "GET /boom" in record.getMessage()
    assert record.exc_info[0] is ValueError


def test_storage_bad_component_still_400(caplog):
    caplog.set_level(logging.WARNING)

    response = _client().get("/runs", params={"verstr": ".."})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid record name: '..'"}
    (record,) = _warnings(caplog)
    assert "GET /runs" in record.getMessage()
