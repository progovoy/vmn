"""A server with a store workspace and a checkout: the startup warm-up
watches every app, the store's stay kept warm (refreshed with nobody
watching), the checkout's idle out; the diag dump says which is which."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.local import LocalSnapshotStorage

STORE_APP, REPO_APP = "store_app", "repo_app"


def _save(storage, app_name):
    storage.save(app_name, "1.0.0-dev.a",
                 {"verstr": "1.0.0-dev.a", "timestamp": "2026-01-01T00:00:00Z"}, {})


def _app(tmp_path, **opts):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _save(open_storage(root=local_store_root(str(repo)), area="runs"), REPO_APP)
    store = tmp_path / "store"
    _save(LocalSnapshotStorage(str(store), area="runs"), STORE_APP)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("repo", str(repo))
    manager.add_store("st", f"file://{os.path.abspath(store)}")
    return create_app(manager, background_refresh=True, **opts)


def _kept_warm(app):
    return {getattr(index, "app_name", None): watch.keep_warm
            for index, watch in app.state.refresher.watched()}


@pytest.mark.parametrize("opts, expected", [
    ({}, {STORE_APP: True, REPO_APP: False}),
    ({"keep_warm": True}, {STORE_APP: True, REPO_APP: True}),
    ({"keep_warm": False}, {STORE_APP: False, REPO_APP: False}),
])
def test_the_startup_warm_up_watches_every_app_kept_warm_by_kind(tmp_path, opts, expected):
    app = _app(tmp_path, **opts)
    try:
        with TestClient(app):
            assert app.state.warmed.wait(30)
            assert _kept_warm(app) == expected
    finally:
        app.state.refresher.stop()


def test_the_diag_dump_says_which_index_is_kept_warm(tmp_path):
    app = _app(tmp_path)
    try:
        with TestClient(app) as client:
            assert app.state.warmed.wait(30)
            watched = client.get("/api/v1/diag").json()["sections"]["indexes"]["watched"]
    finally:
        app.state.refresher.stop()
    assert {e["app"]: e["keep_warm"] for e in watched} == {STORE_APP: True, REPO_APP: False}
