"""Every request the ui serves runs its fan-outs in the request lane
(:func:`vmn_exp.storage.fanout.serving_request`), on its worker thread too;
the server's own background threads don't."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from vmn_exp.storage import fanout  # noqa: E402


def test_a_sync_route_reads_in_the_request_lane(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    app = create_app(WorkspaceManager(os.path.join(tmp_path, "ui")))
    seen = []

    def probe():
        seen.append(fanout._SERVING.get())
        return {}

    app.add_api_route("/lane-probe", probe)
    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the SPA fallback

    with TestClient(app) as client:
        assert client.get("/lane-probe").status_code == 200

    assert seen == [True]
    assert fanout._SERVING.get() is False
