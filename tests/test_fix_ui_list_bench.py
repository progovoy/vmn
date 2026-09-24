"""Scale guard for leaderboard polls at 5k runs: once warm, a list request
must not list every record's files, and the status/tree/filter/sort pipeline
runs at most once per index generation. Counts calls instead of timing, so it
cannot flake on a loaded box."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.ui import leaderboard_cache

APP = "app"
RUNS = 5000
REQUESTS = 20
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _seed(root):
    base = os.path.join(root, ".vmn", APP, "experiments")
    for i in range(RUNS):
        verstr = f"0.0.1-dev.abc1234.def5678.r{i}"
        folder = os.path.join(base, verstr)
        os.makedirs(folder)
        meta = {"verstr": verstr, "timestamp": f"2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}Z"}
        with open(os.path.join(folder, "metadata.yml"), "w") as f:
            yaml.dump(meta, f)
        with open(os.path.join(folder, "log.w.jsonl"), "w") as f:
            f.write(json.dumps({"timestamp": "t", "type": "metrics", "values": {"loss": i}}) + "\n")
        with open(os.path.join(folder, "run_state.yml"), "w") as f:
            f.write("state: finished\nexit_code: 0\n")


@pytest.fixture
def listed(monkeypatch):
    counts = {"full": 0, "records": 0}
    real = LocalSnapshotStorage.list_files

    def counted(self, app_name, keys=None):
        files = real(self, app_name, keys=keys)
        counts["full"] += keys is None
        counts["records"] += len(files)
        return files

    monkeypatch.setattr(LocalSnapshotStorage, "list_files", counted)
    return counts


@pytest.fixture
def pipeline(monkeypatch):
    calls = {"annotate": 0, "sort": 0}
    real_tree, real_sort = leaderboard_cache.annotate_rows, leaderboard_cache.sort_rows

    def tree(*a, **kw):
        calls["annotate"] += 1
        return real_tree(*a, **kw)

    def sort(*a, **kw):
        calls["sort"] += 1
        return real_sort(*a, **kw)

    monkeypatch.setattr(leaderboard_cache, "annotate_rows", tree)
    monkeypatch.setattr(leaderboard_cache, "sort_rows", sort)
    return calls


def test_warm_list_polls_do_no_per_record_work(tmp_path, listed, pipeline):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    _seed(str(root))
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    app = create_app(manager, background_refresh=True)
    client = TestClient(app)
    try:
        warm = client.get(f"{BASE}?sort=loss&limit=50")
        assert warm.json()["total"] == RUNS
        listed.update(full=0, records=0)
        pipeline.update(annotate=0, sort=0)

        for i in range(REQUESTS):
            page = client.get(f"{BASE}?sort=loss&limit=50&offset={50 * i}")
            assert page.status_code == 200
            assert len(page.json()["rows"]) == 50
    finally:
        app.state.refresher.stop()

    assert listed["full"] == 0
    assert listed["records"] < RUNS // 10
    assert pipeline == {"annotate": 0, "sort": 0}
