"""No mutating route answers 500 on a wrong-typed request body, and no job
starts with a non-str argv element (plan 42 E12a).

The sweep sends every POST/PUT/PATCH/DELETE route of ``create_app`` each
known body field as an int, a list, a dict, null and a very long string, one
field at a time on top of a plausible body, against a git workspace and a
store workspace. Jobs are recorded, never run; a store action's in-process
call runs inline, and a TypeError or AttributeError from it fails the sweep.
"""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from test_docs_ui_endpoints import _walk  # noqa: E402

from vmn_exp.storage.areas import local_store_root  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.job_argv import ACTIONS  # noqa: E402
from vmn_exp.ui.jobs_store import STORE_ACTIONS  # noqa: E402
from vmn_exp.core.real_io import real_io  # noqa: E402

TOKEN = "t"
ISSUER = "https://idp.example"
RUN = "0.0.1-dev.a"
HOSTILE = (7, [1], {"a": 1}, None, "x" * 20_000)
# Name "ws" exists, so adding a workspace never clones a remote.
PLAUSIBLE = {
    "name": "ws", "path": ".", "verstr": RUN, "verstrs": [RUN], "text": "{}",
    "note": "n", "target": f"run:app:{RUN}", "title": "T", "body": "b",
    "base": 1, "message": "m", "rev": 1, "data": {}, "release_mode": "patch",
    "prerelease": "rc", "keep": 1, "older_than": "1d", "metrics": {"acc": 1},
    "set": {"k": "v"}, "remove": ["k"], "step": 1, "scope": "", "q": "",
    "status": "active", "archived": False, "dry_run": True, "alias": "prod",
    "version": 1, "expect": 1, "run": {"app": "app", "verstr": RUN},
    "artifact_path": "model", "artifact_uri": "file:///m", "description": "d",
    "model": "m", "roles": {}, "ttl_sec": 60, "keys": ["acc"], "x": "step",
    "max_points": 10, "device_code": "d", "reply_to": "c", "anchor": "a",
    "resolved": True, "pinned": True, "remote": "",
}
# Swept, but not in the plausible body (step_min/step_max refuse an ``x``).
FIELDS = tuple(PLAUSIBLE) + ("step_min", "step_max")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# RID and CID are the report and comment each test seeds.
PATH_VALUES = {
    "app_tag": "app", "target": f"run:app:{RUN}", "comment_id": "CID",
    "model_name": "m", "alias": "prod", "version_n": "1", "rid": "RID",
    "token_id": "x",
}


def _seed_runs(storage):
    storage.save("app", RUN, {"verstr": RUN, "timestamp": "2026-01-01T00:00:00Z"}, {})


def _manager(tmp_path):
    from vmn_exp.ui.workspaces import WorkspaceManager

    checkout = tmp_path / "checkout"
    os.makedirs(checkout / ".git")
    _seed_runs(open_storage(root=local_store_root(str(checkout)), area="runs"))
    _seed_runs(open_storage(root=str(tmp_path / "store"), area="runs"))
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(checkout))
    manager.add_store("st", f"file://{tmp_path / 'store'}")
    return manager


class _Recorder:
    """Stands in for the job runner's submits: records each job's command
    and runs a store action's call inline."""

    def __init__(self):
        self.commands, self.crashes = [], []

    def submit(self, ws, cwd, command):
        return self._job(command), None

    def submit_call(self, ws, command, call):
        try:
            call()
        except (TypeError, AttributeError) as exc:
            self.crashes.append(repr(exc))
        except Exception:
            pass
        return self._job(command), None

    def submit_bulk(self, ws, command, resolve, act):
        return self._job(command), None

    def _job(self, command):
        self.commands.append(command)
        return {"id": "j", "command": command, "status": "running"}

    def install(self, jobs):
        jobs.submit, jobs.submit_call, jobs.submit_bulk = (
            self.submit, self.submit_call, self.submit_bulk)


class _IdP:
    """Discovery, a device grant and a token endpoint always pending."""

    def get_json(self, url):
        return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "device_authorization_endpoint": f"{ISSUER}/device"}

    def post_form(self, url, data):
        if url == f"{ISSUER}/device":
            return {"device_code": "idp", "user_code": "U", "expires_in": 60}
        return {"error": "authorization_pending"}


def _app(tmp_path):
    from vmn_exp.ui.auth import AuthenticatorChain
    from vmn_exp.ui.auth.oidc import OIDCAuthenticator, OIDCConfig
    from vmn_exp.ui.control_plane import SQLiteControlPlane
    from vmn_exp.ui.server import create_app

    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    config = OIDCConfig(issuer=ISSUER, client_id="vmn-exp",
                        redirect_uri="https://vmn.example/auth/callback")
    oidc = OIDCAuthenticator(config, cp, object(), http=_IdP())
    return create_app(_manager(tmp_path), io=real_io(), token=TOKEN,
                      auth=AuthenticatorChain([oidc]), control_plane=cp)


def _mutating_routes():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        return sorted({(method, path) for path, route in _walk(_app(Path(tmp)).routes)
                       for method in getattr(route, "methods", None) or ()
                       if method in MUTATING})


def _cases():
    for method, path in _mutating_routes():
        workspaces = ("ws", "st") if "{ws_name}" in path else (None,)
        actions = ACTIONS + tuple(STORE_ACTIONS) if "{action}" in path else (None,)
        for ws in workspaces:
            for action in dict.fromkeys(actions):
                yield method, _fill(path, ws, action)


def _fill(path, ws, action):
    values = dict(PATH_VALUES, ws_name=ws, action=action)
    for name, value in values.items():
        path = path.replace(f"{{{name}:path}}", str(value)).replace(f"{{{name}}}", str(value))
    return path


def _bodies():
    for field in FIELDS:
        for value in HOSTILE:
            yield f"{field}={type(value).__name__}", dict(PLAUSIBLE, **{field: value})


def _client(tmp_path, recorder):
    app = _app(tmp_path)
    recorder.install(app.state.jobs)
    return TestClient(app, base_url="https://vmn.example", raise_server_exceptions=False,
                      headers={"Authorization": f"Bearer {TOKEN}"})


def _seeded(client, path):
    """*path* with RID and CID naming a report and a comment of its
    workspace, and model ``m`` version 1 there."""
    ws = path.split("/")[4] if path.startswith("/api/v1/workspaces/") else None
    if ws is None:
        return path
    api = f"/api/v1/workspaces/{ws}"
    rid = client.post(f"{api}/reports", json={"title": "T"}).json()["rid"]
    cid = client.post(f"{api}/comments", json={"target": f"run:app:{RUN}", "text": "c"}).json()["id"]
    client.post(f"{api}/models/m/versions", json={"run": {"app": "app", "verstr": RUN}})
    return path.replace("RID", rid).replace("CID", cid)


def _sweep(client, method, path):
    for case, body in _bodies():
        yield case, client.request(method, path, json=body)


@pytest.mark.parametrize("method,path", list(_cases()))
def test_no_mutating_route_answers_500_on_wrong_typed_body(tmp_path, method, path):
    recorder = _Recorder()
    client = _client(tmp_path, recorder)
    path = _seeded(client, path)

    failures = [(case, r.status_code) for case, r in _sweep(client, method, path)
                if r.status_code >= 500]

    assert failures == []
    assert recorder.crashes == []
    assert [c for c in recorder.commands
            if not all(isinstance(t, str) for t in c)] == []


BODY_ROUTES = [
    ("POST", "/api/v1/workspaces"),
    ("POST", "/api/v1/tokens"),
    ("POST", "/auth/device/token"),
    ("POST", "/api/v1/workspaces/ws/apps/app/series"),
    ("POST", "/api/v1/workspaces/ws/apps/app/actions/stamp"),
    ("PUT", "/api/v1/workspaces/st/apps/app/settings"),
    ("POST", "/api/v1/workspaces/st/comments"),
    ("POST", "/api/v1/workspaces/st/reports"),
    ("POST", "/api/v1/workspaces/st/models/m/aliases"),
]


@pytest.mark.parametrize("method,path", BODY_ROUTES)
@pytest.mark.parametrize("body", [[1, 2], "s", 3])
def test_non_object_body_is_422(tmp_path, method, path, body):
    client = _client(tmp_path, _Recorder())

    assert client.request(method, path, json=body).status_code == 422
