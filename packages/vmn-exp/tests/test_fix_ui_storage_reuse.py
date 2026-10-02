"""Scale guard: run-detail, log and series requests reuse the workspace's
experiment storage instead of building one per request. A new storage object
resolves its root with ``realpath`` (an ``lstat`` per path component) the
first time the parsed-log cache asks its identity, and under load every such
syscall waits for the GIL behind busy request threads."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.areas import local_store_root

APP = "app"


def test_detail_log_and_series_requests_reuse_one_storage(tmp_path, monkeypatch):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    st = LocalSnapshotStorage(local_store_root(str(root)), area="runs")
    verstr = "0.0.1-dev.abc.r1"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "metrics", "values": {"loss": 1}})

    built = []
    real_init = LocalSnapshotStorage.__init__

    def counting(self, *args, **kwargs):
        built.append(1)
        real_init(self, *args, **kwargs)

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    app = create_app(manager, background_refresh=True)
    base = f"/api/v1/workspaces/ws/apps/{APP}"
    try:
        with TestClient(app) as client:
            assert client.get(f"{base}/experiments/{verstr}").status_code == 200
            monkeypatch.setattr(LocalSnapshotStorage, "__init__", counting)
            for _ in range(10):
                assert client.get(f"{base}/experiments/{verstr}").status_code == 200
                assert client.get(f"{base}/experiments/{verstr}/log").status_code == 200
                body = {"verstrs": [verstr], "keys": None, "max_points": 100}
                assert client.post(f"{base}/series", json=body).status_code == 200
    finally:
        app.state.refresher.stop()
    assert built == []
