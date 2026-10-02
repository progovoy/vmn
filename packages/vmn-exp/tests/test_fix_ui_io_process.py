"""The ui's background refresher runs each watched index's filesystem work in
an I/O helper process (see vmn_exp.core.index_io_process): under request load
a refresh doing its own stat/open calls starved on the GIL and new runs never
showed up. Stopping the refresher stops the helpers."""
import os

import pytest

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui.refresher import InlineRefresher, Refresher
from vmn_exp.storage.areas import local_store_root

APP = "app"


def _seed(root, n=3):
    st = LocalSnapshotStorage(local_store_root(str(root)), area="runs")
    for i in range(n):
        v = f"0.0.1-dev.abc.r{i}"
        st.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
    return st


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_a_background_watched_index_uses_a_helper_until_stopped(tmp_path):
    index = ExperimentIndex(_seed(tmp_path), APP, cache_path=str(tmp_path / "idx.sqlite"))
    refresher = Refresher(interval_sec=0.02, idle_sec=60)
    snap = refresher.snapshot(index)
    assert len(snap.rows) == 3
    helper = index._io._proc.pid
    assert _alive(helper)

    refresher.stop()
    os.waitpid(helper, os.WNOHANG) if _alive(helper) else None
    assert index._io is None
    assert not _alive(helper)


def test_an_inline_refreshed_index_stays_in_process(tmp_path):
    index = ExperimentIndex(_seed(tmp_path), APP, cache_path=str(tmp_path / "idx.sqlite"))
    InlineRefresher().snapshot(index)
    assert index._io is None


def test_the_server_lists_through_the_helper(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    _seed(root)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    app = create_app(manager, background_refresh=True)
    try:
        with TestClient(app) as client:
            body = client.get(f"/api/v1/workspaces/ws/apps/{APP}/experiments?limit=10").json()
        assert [r["verstr"] for r in body["rows"]] == [f"0.0.1-dev.abc.r{i}" for i in range(3)]
        watched = list(app.state.refresher._watches)
        assert watched and all(index._io is not None for index in watched)
    finally:
        app.state.refresher.stop()
    assert all(index._io is None for index in watched)
