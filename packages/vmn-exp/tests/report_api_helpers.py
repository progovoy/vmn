"""Shared fixtures for the reports/comments route tests."""
from fastapi.testclient import TestClient

from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.principal import Principal

WS = "/api/v1/workspaces/main"


class HeaderAuth:
    """``X-User: <id>:<role>`` -> a principal holding *role* everywhere."""

    def authenticate(self, request):
        raw = request.headers.get("X-User")
        if not raw:
            return None
        uid, role = raw.split(":")
        return Principal(id=uid, name=uid.title(), roles={"*": role})


def make_client(tmp_path, read_only=False, auth=False):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    (tmp_path / ".vmn").mkdir(exist_ok=True)
    data_dir = tmp_path / "ui_data"
    data_dir.mkdir(exist_ok=True)
    manager = WorkspaceManager(str(data_dir))
    if manager.get("main") is None:
        manager.attach_path("main", str(tmp_path))
    chain = AuthenticatorChain([HeaderAuth()]) if auth else None
    return TestClient(create_app(manager, read_only=read_only, auth=chain))


def user(uid, role):
    return {"X-User": f"{uid}:{role}"}


def create_report(client, title="T", body="# hi", headers=None):
    r = client.post(f"{WS}/reports", json={"title": title, "body": body}, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()["rid"]
