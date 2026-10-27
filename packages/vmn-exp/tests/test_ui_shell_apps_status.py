"""GET .../workspaces/{ws}/apps-status: every app's status summary in one
request, and experiments-status's app_not_found against a git checkout."""
import os
import subprocess

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}
ZERO = {"created": 0, "running": 0, "stuck": 0, "succeeded": 0, "failed": 0}


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


def _save_runs(storage, app, count):
    for i in range(count):
        v = f"0.0.1-dev.{i:04d}abcd.{i}"
        storage.save(app, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})


def _manager(tmp_path):
    from vmn_exp.ui.workspaces import WorkspaceManager

    return WorkspaceManager(os.path.join(tmp_path, "ui_data"))


def _store_client(tmp_path, apps):
    from vmn_exp.ui.server import create_app

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for app, count in apps.items():
        _save_runs(storage, app, count)
    manager = _manager(tmp_path)
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


def _git_client(tmp_path, conf_apps, runs):
    """A checkout whose ``.vmn/<app>/conf.yml`` exists for *conf_apps*;
    *runs* ``{app: count}`` go to its repo-local store."""
    from vmn_exp.ui.server import create_app

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for app in conf_apps:
        conf_dir = repo / ".vmn" / app
        conf_dir.mkdir(parents=True)
        (conf_dir / "conf.yml").write_text("conf: {}\n")
    store = f"file://{repo}/.vmn/store"
    for app, count in runs.items():
        _save_runs(open_storage(store, area=RUNS), app, count)
    manager = _manager(tmp_path)
    manager.attach_path("ws", str(repo))
    return TestClient(create_app(manager))


def _get(client, path, status=200):
    r = client.get(f"/api/v1/workspaces/ws/{path}")
    assert r.status_code == status, r.text
    return r.json()


def test_apps_status_has_every_app(tmp_path):
    client = _store_client(tmp_path, {"app_a": 2, "root_app/svc": 1})
    body = _get(client, "apps-status")
    assert sorted(body) == ["app_a", "root_app-svc"]
    assert body["app_a"] == _get(client, "apps/app_a/experiments-status")
    assert body["root_app-svc"]["total"] == 1
    assert body["app_a"] == {
        "total": 2, "counts": dict(ZERO, created=2), "never_started": 0, "lost": 0,
        "failed_recent": 0, "rollup": None,
    }


def test_apps_status_etag_and_304(tmp_path):
    client = _store_client(tmp_path, {"app_a": 1})
    r = client.get("/api/v1/workspaces/ws/apps-status")
    again = client.get("/api/v1/workspaces/ws/apps-status",
                       headers={"If-None-Match": r.headers["ETag"]})
    assert again.status_code == 304


def test_apps_status_of_an_unknown_workspace_is_404(tmp_path):
    client = _store_client(tmp_path, {"app_a": 1})
    assert client.get("/api/v1/workspaces/nope/apps-status").status_code == 404


def test_git_app_with_conf_and_no_runs_is_zero_counts(tmp_path):
    client = _git_client(tmp_path, ["my_app"], {})
    body = _get(client, "apps/my_app/experiments-status")
    assert body == {"total": 0, "counts": ZERO, "never_started": 0, "lost": 0,
                    "failed_recent": 0, "rollup": None}
    assert _get(client, "apps-status") == {"my_app": body}


def test_git_app_with_runs_only_is_known(tmp_path):
    client = _git_client(tmp_path, [], {"run_only": 2})
    assert _get(client, "apps/run_only/experiments-status")["total"] == 2


def test_git_unknown_app_is_app_not_found(tmp_path):
    client = _git_client(tmp_path, ["my_app"], {})
    body = _get(client, "apps/nope/experiments-status", status=404)
    assert body["code"] == "app_not_found"
    assert "nope" in body["detail"]
