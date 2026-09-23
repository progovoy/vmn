"""vmn ui request hardening: static-file containment, cross-site and
DNS-rebinding defence, and path-param validation.

Every attack here was reproduced against the unpatched server first: the SPA
fallback served /etc/passwd with a token set, an empty cross-site ``no-cors``
POST queued ``vmn release``, and ``..-..-secret`` read a conf.yml outside the
workspace.
"""
import asyncio
import os
import urllib.parse

import pytest

pytest.importorskip("fastapi")
from starlette.testclient import TestClient

from version_stamp.ui import jobs as jobs_mod
from version_stamp.ui.server import create_app
from version_stamp.ui.workspaces import WorkspaceManager

SECRET = "db_password=hunter2"


def _asgi_get(app, raw_path, headers=()):
    """Drive the ASGI app with the scope uvicorn builds: ``path`` is the
    percent-decoded raw path and is *not* dot-segment normalized."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": urllib.parse.unquote(raw_path),
        "raw_path": raw_path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8265")] + list(headers),
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8265),
    }
    out = {"status": None, "body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return out["status"], out["body"]


@pytest.fixture
def layout(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    (ws / ".vmn").mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "conf.yml").write_text(f'conf:\n  leaked: "{SECRET}"\n')
    (secret / "passwd").write_text(SECRET)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(ws))
    return tmp_path, manager


@pytest.fixture
def queued(monkeypatch):
    """Record submitted jobs instead of running ``vmn`` subprocesses."""
    commands = []

    def submit(self, ws_name, cwd, command):
        commands.append(command)
        return {"id": "x", "command": command, "status": "running"}, None

    monkeypatch.setattr(jobs_mod.JobRunner, "submit", submit)
    return commands


# ---------------------------------------------------------------------------
# SPA fallback containment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "//etc/passwd",
        "/" + "..%2f" * 16 + "etc%2fpasswd",
        "/" + "../" * 16 + "etc/passwd",
    ],
)
def test_spa_fallback_never_serves_files_outside_static(layout, raw):
    _, manager = layout
    app = create_app(manager, token="s3cret")
    status, body = _asgi_get(app, raw)
    assert b"root:" not in body and b"User Database" not in body
    assert status in (200, 404)


def test_spa_fallback_cannot_reach_data_dir_files(layout):
    tmp_path, manager = layout
    app = create_app(manager, token="s3cret")
    target = str(tmp_path / "secret" / "passwd")
    status, body = _asgi_get(app, "/" + target)
    assert SECRET.encode() not in body


def test_spa_fallback_still_serves_client_routes(layout):
    _, manager = layout
    client = TestClient(create_app(manager))
    static_index = os.path.join(
        os.path.dirname(create_app.__code__.co_filename), "static", "index.html"
    )
    if not os.path.isfile(static_index):
        pytest.skip("web bundle not built")
    r = client.get("/workspaces/ws/apps/app")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


# ---------------------------------------------------------------------------
# Cross-site requests and DNS rebinding
# ---------------------------------------------------------------------------

ACTION = "/api/v1/workspaces/ws/apps/my_app/actions/{}"


@pytest.mark.parametrize("action", ["release", "goto"])
def test_empty_cross_site_post_does_not_queue_a_job(layout, queued, action):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.post(ACTION.format(action), headers={"Origin": "https://evil.example"})
    assert r.status_code in (403, 415)
    assert queued == []


def test_post_without_json_content_type_is_rejected(layout, queued):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.post(ACTION.format("release"), content=b"", headers={})
    assert r.status_code == 415
    r = client.post(
        ACTION.format("release"),
        content=b"{}",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 415
    assert queued == []


def test_same_origin_json_post_is_accepted(layout, queued):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.post(
        ACTION.format("release"), json={}, headers={"Origin": "http://testserver"}
    )
    assert r.status_code == 202
    assert queued == [["vmn", "release", "my_app"]]


def test_json_post_from_foreign_origin_is_forbidden(layout, queued):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.post(
        ACTION.format("release"), json={}, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert queued == []


def test_foreign_referer_counts_when_origin_is_absent(layout, queued):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.post(
        ACTION.format("release"),
        json={},
        headers={"Referer": "https://evil.example/page"},
    )
    assert r.status_code == 403
    assert queued == []


def test_delete_from_foreign_origin_is_forbidden(layout):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.delete("/api/v1/workspaces/ws", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert manager.get("ws") is not None


def test_rebound_host_is_rejected_without_a_token(layout):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.get("/api/v1/workspaces", headers={"Host": "attacker.example"})
    assert r.status_code == 403


@pytest.mark.parametrize("host", ["localhost:8265", "127.0.0.1:8265", "[::1]:8265"])
def test_loopback_hosts_are_allowed(layout, host):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.get("/api/v1/workspaces", headers={"Host": host})
    assert r.status_code == 200


def test_allowed_hosts_extend_the_allowlist(layout):
    _, manager = layout
    client = TestClient(create_app(manager, allowed_hosts=["vmn.internal"]))
    r = client.get("/api/v1/workspaces", headers={"Host": "vmn.internal:8265"})
    assert r.status_code == 200
    r = client.get("/api/v1/workspaces", headers={"Host": "other.internal"})
    assert r.status_code == 403


def test_origin_matching_an_allowed_host_is_accepted(layout, queued):
    """A reverse proxy may rewrite Host; an allowlisted Origin still passes."""
    _, manager = layout
    client = TestClient(create_app(manager, allowed_hosts=["vmn.company.com"]))
    r = client.post(
        ACTION.format("release"),
        json={},
        headers={"Origin": "https://vmn.company.com"},
    )
    assert r.status_code == 202


def test_token_mode_does_not_restrict_host(layout):
    _, manager = layout
    client = TestClient(create_app(manager, token="t"))
    r = client.get(
        "/api/v1/workspaces",
        headers={"Host": "vmn.company.com", "Authorization": "Bearer t"},
    )
    assert r.status_code == 200


def test_allowed_host_cli_flag_is_repeatable():
    from version_stamp.cli.args import parse_user_commands

    args = parse_user_commands(
        ["ui", "--allowed-host", "a.internal", "--allowed-host", "b.internal"]
    )
    assert args.allowed_host == ["a.internal", "b.internal"]
    assert parse_user_commands(["ui"]).allowed_host is None


# ---------------------------------------------------------------------------
# Path params never escape the workspace
# ---------------------------------------------------------------------------


def test_app_name_traversal_is_rejected(layout):
    _, manager = layout
    client = TestClient(create_app(manager, token="t", read_only=True))
    r = client.get(
        "/api/v1/workspaces/ws/apps/..-..-secret/config",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 400
    assert SECRET not in r.text


@pytest.mark.parametrize(
    "app_tag", ["..-..-secret", "a-..-b", ".-x", "x-branch_conf", "a--b"]
)
def test_invalid_app_names_are_400(layout, app_tag):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.get(f"/api/v1/workspaces/ws/apps/{app_tag}/experiments")
    assert r.status_code == 400


def test_valid_nested_app_name_still_works(layout):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.get("/api/v1/workspaces/ws/apps/root_app-svc/experiments")
    assert r.status_code == 200


@pytest.mark.parametrize("raw_verstr", ["%2E%2E", "a..b", "a%5Cb"])
def test_unsafe_verstr_is_400(layout, raw_verstr):
    # Raw ASGI, not TestClient: httpx strips a literal ``..`` segment client-side,
    # but uvicorn hands ``%2E%2E`` to the app decoded and un-normalized.
    _, manager = layout
    app = create_app(manager)
    status, _ = _asgi_get(app, f"/api/v1/workspaces/ws/apps/app/experiments/{raw_verstr}")
    assert status == 400


@pytest.mark.parametrize("name", ["..", "a\\b", "..%5Cx"])
def test_unsafe_artifact_name_is_400(layout, name):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.get(
        f"/api/v1/workspaces/ws/apps/app/experiments/0.0.1-dev.a/artifacts/{name}"
    )
    assert r.status_code in (400, 404)
    assert SECRET not in r.text


def test_unsafe_diff_refs_are_400(layout):
    _, manager = layout
    client = TestClient(create_app(manager))
    r = client.get(
        "/api/v1/workspaces/ws/apps/app/experiments-diff",
        params={"v": "../../secret", "to": "latest"},
    )
    assert r.status_code == 400
