"""Plan 28 P4 over HTTP: an app's team views (settings/conf
``experiment.ui.views``) ride on its ``experiments-status``, the payload
every app page already reads, so a page knows its default view at once."""
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.app_settings_store import write_settings  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
SETTINGS = """\
ui:
  views:
    - {name: health, page: runs, search: 'show=t:health', default: true}
    - {name: by kind, page: job, search: '?group=tags.kind'}
"""
SERVED = [
    {"name": "health", "page": "runs", "search": "?show=t:health", "default": True},
    {"name": "by kind", "page": "job", "search": "?group=tags.kind", "default": False},
]


def _run(storage, n):
    verstr = f"0.0.1-dev.abc1234.def5678.r{n}"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{n}Z"}, {})
    storage.save_file(APP, verstr, "run_state.yml", "state: finished\nexit_code: 0\n")


@pytest.fixture
def store(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    _run(storage, 1)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    return (lambda: TestClient(create_app(manager))), storage


def _status(client, **params):
    r = client.get(f"{BASE}/experiments-status", params=params)
    assert r.status_code == 200, r.text
    return r


def test_the_status_carries_the_team_views(store):
    client_of, storage = store
    write_settings(storage, APP, SETTINGS)
    assert _status(client_of()).json()["views"] == SERVED


def test_no_views_no_field(store):
    client_of, _ = store
    assert "views" not in _status(client_of()).json()


def test_a_settings_change_moves_the_views_and_the_etag(store):
    client_of, storage = store
    write_settings(storage, APP, SETTINGS)
    client = client_of()
    first = _status(client)
    r = client.put(f"{BASE}/settings", json={"text": "ui: {views: []}\n"})
    assert r.status_code == 200, r.text
    second = _status(client)
    assert "views" not in second.json()
    assert second.headers["etag"] != first.headers["etag"]


def test_a_scoped_status_carries_no_views(store):
    client_of, storage = store
    write_settings(storage, APP, SETTINGS)
    body = _status(client_of(), scope="0.0.1-dev.abc1234.def5678.r1").json()
    assert "views" not in body


def test_a_checkout_conf_names_team_views_too(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = LocalSnapshotStorage(str(root / ".vmn" / "store"), "runs")
    _run(storage, 1)
    write_settings(storage, APP, SETTINGS)
    os.makedirs(root / ".vmn" / APP)
    views = [{"name": "failed", "page": "jobs", "search": "status=failed"}]
    with open(root / ".vmn" / APP / "conf.yml", "w") as f:
        yaml.dump({"conf": {"experiment": {"ui": {"views": views}}}}, f)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    assert _status(TestClient(create_app(manager))).json()["views"] == [
        {"name": "failed", "page": "jobs", "search": "?status=failed", "default": False}]
