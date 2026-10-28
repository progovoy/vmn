"""No request waits for a cold store index's first load: with every record
read the index's own threads make held back (its metadata.yml loads), the
routes a dashboard, ⌘K and a metrics scrape hit answer at once. At 588k S3
runs that first load takes hours."""
import threading
import time

import pytest

pytest.importorskip("fastapi")
moto = pytest.importorskip("moto")
import boto3  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "app"
WS = "/api/v1/workspaces/ws"
BASE = f"{WS}/apps/{APP}"
RUN = "0.0.1"
PROMPT_SEC = 3.0
INDEX_THREADS = ("vmn-index", "vmn-ui-refresh")

ROUTES = [
    "/api/v1/meta",
    "/api/v1/workspaces",
    f"{WS}/apps",
    f"{WS}/apps-status",
    f"{BASE}/experiments?offset=0&limit=50",
    f"{BASE}/experiments?top=jobs&limit=50",
    f"{BASE}/experiments?top=singles&limit=50",
    f"{BASE}/experiments?group=status",
    f"{BASE}/experiments-status",
    f"{BASE}/experiments-facets",
    f"{BASE}/experiments-columns",
    f"{BASE}/metrics-schema",
    f"{BASE}/experiments/{RUN}",
    f"{BASE}/experiments/{RUN}/baselines",
    f"{BASE}/experiments/{RUN}/summary",
    f"{BASE}/experiments/{RUN}/lineage",
    f"{BASE}/experiments/{RUN}/sweep",
    f"{BASE}/experiments/{RUN}/log?offset=0&limit=50",
    f"{BASE}/experiments/{RUN}/failures",
    f"{BASE}/experiments/{RUN}/patch",
    f"{BASE}/experiments/{RUN}/metric-keys",
    f"{BASE}/experiments/{RUN}/similar",
    f"{BASE}/experiments-importance?metric=loss",
    f"{BASE}/similar?text=loss",
    f"{WS}/models",
    f"{BASE}/search?text=loss",
    "/api/v1/search?text=loss",
    "/metrics",
]


def _held_metadata_loads(monkeypatch, release):
    """Hold every ``metadata.yml`` load the index makes (its load threads,
    its refresher) until *release*; a request's own reads (a run page's, on
    the detail pool) go through."""
    real = S3SnapshotStorage.load_file

    def load_file(self, app_name, verstr, filename):
        if filename == "metadata.yml" and threading.current_thread().name.startswith(INDEX_THREADS):
            release.wait(60)
        return real(self, app_name, verstr, filename)

    monkeypatch.setattr(S3SnapshotStorage, "load_file", load_file)


@pytest.fixture
def cold(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    release = threading.Event()
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        storage = S3SnapshotStorage("vmn-bucket", prefix="st/runs")
        for i in range(3):
            v = f"0.0.{i}"
            storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        _held_metadata_loads(monkeypatch, release)
        from vmn_exp.ui.server import create_app
        from vmn_exp.ui.workspaces import WorkspaceManager

        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_store("ws", "s3://vmn-bucket/st")
        app = create_app(manager, background_refresh=True)
        with TestClient(app) as client:
            try:
                yield client, release
            finally:
                release.set()
                app.state.refresher.stop()


def _answered_within(client, path, timeout):
    """The response's status code, or None when it took over *timeout*."""
    answer = []
    thread = threading.Thread(target=lambda: answer.append(client.get(path).status_code),
                              daemon=True)
    thread.start()
    thread.join(timeout)
    return answer[0] if answer else None


@pytest.mark.serial  # timed: 3 s a route
def test_the_main_routes_answer_while_a_cold_index_loads(cold):
    client, release = cold
    status = client.get(f"{BASE}/experiments-status").json()
    assert status["indexing"]["loaded"] == 0  # held: nothing published yet

    slow = {}
    for path in ROUTES:
        started = time.monotonic()
        code = _answered_within(client, path, PROMPT_SEC)
        if code is None or code >= 500:
            slow[path] = code if code else f"> {PROMPT_SEC}s"
        assert time.monotonic() - started < PROMPT_SEC + 1
    assert slow == {}
    assert client.get(f"{BASE}/experiments-status").json()["indexing"]["loaded"] == 0
