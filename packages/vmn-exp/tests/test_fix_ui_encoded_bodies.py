"""Scale guard: the dashboard's most common requests (the first leaderboard
page, the chart columns) are identical across clients within an index
generation. Their ETag is known before the payload is built, so the encoded
— and gzipped — body is kept per ETag: rendering and compressing a 200-row
page cost more than serving it from the memo. Counts calls, cannot flake."""
import gzip

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui import responses

APP = "app"


def test_identical_list_requests_encode_their_body_once(tmp_path, monkeypatch):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    st = LocalSnapshotStorage(str(root), subdir="experiments")
    for i in range(300):
        v = f"0.0.1-dev.abc.r{i}"
        st.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z"}, {})
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    app = create_app(manager, background_refresh=True)
    renders, compressions = [], []
    real_render, real_compress = responses.render_json, gzip.compress
    monkeypatch.setattr(responses, "render_json", lambda p: renders.append(1) or real_render(p))
    monkeypatch.setattr(gzip, "compress", lambda *a, **k: compressions.append(1) or real_compress(*a, **k))
    url = f"/api/v1/workspaces/ws/apps/{APP}/experiments?offset=0&limit=200"
    try:
        with TestClient(app) as client:
            client.get(url.replace("limit=200", "limit=1"))  # the index's first load
            renders.clear(), compressions.clear()
            bodies = [client.get(url, headers={"Accept-Encoding": "gzip"}) for _ in range(10)]
            plain = client.get(url, headers={"Accept-Encoding": "identity"})
    finally:
        app.state.refresher.stop()

    assert all(r.status_code == 200 and r.headers["content-encoding"] == "gzip" for r in bodies)
    assert len({r.content for r in bodies}) == 1 and len(bodies[0].json()["rows"]) == 200
    assert plain.json() == bodies[0].json() and "content-encoding" not in plain.headers
    assert len(renders) == 1
    assert len(compressions) == 1
