"""api_errors.install answers a ValueError raised under a request with 400
and its message, and logs it at warning with the method, path and stack so
an operator sees server bugs the 400 relabels as client errors.

Every other JSON error carries ``detail`` and ``code`` (plan 42 E12b)."""
import logging

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.files import safe_verstr  # noqa: E402
from vmn_exp.ui import api_errors  # noqa: E402
from vmn_exp.core.real_io import real_io


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


# ---- E12b: one envelope, every JSON error carries detail and code ----------


def _coded_client():
    app = FastAPI()
    api_errors.install(app)

    @app.get("/missing")
    def _missing():
        raise HTTPException(404, "Workspace 'x' not found")

    @app.get("/busy")
    def _busy():
        raise HTTPException(429, "Too many diffs", headers={"Retry-After": "5"})

    @app.get("/coded")
    def _coded():
        raise api_errors.CodedError(404, "No run 'x'", "run_not_found")

    return TestClient(app)


def test_plain_http_exception_has_code():
    client = _coded_client()

    missing = client.get("/missing")
    busy = client.get("/busy")
    unrouted = client.get("/no-such-route")

    assert missing.json() == {"detail": "Workspace 'x' not found", "code": "not_found"}
    assert busy.json() == {"detail": "Too many diffs", "code": "busy"}
    assert busy.headers["Retry-After"] == "5"
    assert unrouted.json() == {"detail": "Not Found", "code": "not_found"}


def test_coded_error_code_wins():
    response = _coded_client().get("/coded")

    assert response.json() == {"detail": "No run 'x'", "code": "run_not_found"}


def test_error_body_keeps_extra_keys():
    body = api_errors.error_body("Not a git repository", "not_a_repo",
                                 reason="not_a_repo", path="/x")

    assert body == {"detail": "Not a git repository", "code": "not_a_repo",
                    "reason": "not_a_repo", "path": "/x"}


def _server(tmp_path, ws_path, **opts):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(ws_path))
    return TestClient(create_app(manager, io=real_io(), **opts))


def _repo(tmp_path, head="ref: refs/heads/main\n"):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(head)
    return root


def test_reason_sites_also_carry_code(tmp_path):
    client = _server(tmp_path, _repo(tmp_path, head="garbage"))

    events = client.get("/api/v1/workspaces/ws/apps/app/events").json()
    tree = client.get("/api/v1/workspaces/ws/apps/app/tree").json()

    assert events["code"] == events["reason"] == "no_live_events"
    assert tree["code"] == tree["reason"] == "not_a_repo"
    assert "path" in tree


def test_401_keeps_auth_hints_and_has_code(tmp_path):
    client = _server(tmp_path, _repo(tmp_path), token="s3cret")

    response = client.get("/api/v1/workspaces")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert response.json()["auth"]["token"] is True


def test_guard_403_has_code(tmp_path):
    client = _server(tmp_path, _repo(tmp_path))

    refused = client.get("/api/v1/workspaces", headers={"host": "attacker.example"})
    unknown_api = client.get("/api/v1/nope")

    assert refused.json() == {"detail": "Host not allowed", "code": "forbidden"}
    assert unknown_api.json() == {"detail": "Not Found", "code": "not_found"}
