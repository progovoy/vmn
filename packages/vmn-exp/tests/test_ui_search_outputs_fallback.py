"""Search rows synced to Postgres carry no ``outputs``: a query reading them
is answered in Python, every other one by the SQL backend."""
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.index import direct_snapshot  # noqa: E402
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log  # noqa: E402
from vmn_exp.snapshot import LocalSnapshotStorage  # noqa: E402
from vmn_exp.ui import routes_search  # noqa: E402

APP = "app"
V = "0.0.1-dev.abc.r1"


class FakeSql:
    def __init__(self):
        self.searched = []

    def sync(self, workspace, app, generation, rows_of):
        pass

    def search(self, workspaces, text, limit, archived=False):
        self.searched.append(text)
        return []


class _Ws:
    name = "ws"


class _Manager:
    def list(self):
        return [_Ws()]


@pytest.fixture
def client(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    append_to_log(storage, APP, V, create_log_entry("artifact", path="m.bin", sha256="ab", size=2))
    flush_log(storage, APP, V)
    snap = direct_snapshot(storage, APP)
    app = FastAPI()
    app.state.manager = _Manager()
    sql = FakeSql()
    routes_search.register(app, "/api", lambda names: iter([("ws", APP, snap)]), sql)
    return TestClient(app), sql


def test_outputs_query_is_filtered_in_python(client):
    http, sql = client
    body = http.get("/api/search", params={"q": 'outputs."m.bin".digest = "sha256:ab"'}).json()
    assert [r["verstr"] for r in body["results"]] == [V]
    assert sql.searched == []


def test_other_queries_push_down(client):
    http, sql = client
    http.get("/api/search", params={"q": "verstr ~ r1"})
    assert sql.searched == ["verstr ~ r1"]


@pytest.mark.parametrize("text,expected", [
    ('outputs."a".digest = "x"', True),
    ('verstr ~ "a" and not outputs."a".size > 1', True),
    ("metrics.loss < 1", False),
    ("", False),
])
def test_references_outputs(text, expected):
    assert routes_search.references_outputs(text) is expected
