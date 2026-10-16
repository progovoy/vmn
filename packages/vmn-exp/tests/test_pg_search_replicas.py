"""``vmn_search_rows`` are written by the replica leading an app's index, on
its refresh; a search request only reads them (plan 25 F5)."""
import threading

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from pg_locks import until  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.search_pg import PgRowSearch  # noqa: E402

APP = "app"
SEARCH = "/api/v1/search"
LIST = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _save(storage, verstr):
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})


def _replica(tmp_path, name, store, pg_dsn, **kw):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / f"data-{name}"))
    manager.add_store("ws", store)
    return TestClient(create_app(manager, search_dsn=pg_dsn, **kw))


def _hits(client):
    response = client.get(SEARCH, params={"q": ""})
    assert response.status_code == 200, response.text
    return [hit["verstr"] for hit in response.json()["results"]]


@pytest.fixture
def store(tmp_path):
    uri = f"file://{tmp_path}/store"
    return uri, open_storage(uri, area=RUNS)


def test_followers_search_what_the_index_leader_refreshed(tmp_path, pg_dsn, store):
    uri, storage = store
    _save(storage, "0.0.1-dev.a.r1")
    leader, first, second = (_replica(tmp_path, n, uri, pg_dsn, cache_dsn=pg_dsn)
                             for n in ("leader", "first", "second"))
    assert leader.get(LIST).status_code == 200  # leads the index, never searches
    assert _hits(first) == ["0.0.1-dev.a.r1"]
    _save(storage, "0.0.1-dev.a.r2")
    assert len(leader.get(LIST).json()) == 2  # the leader's next refresh
    assert _hits(second) == ["0.0.1-dev.a.r1", "0.0.1-dev.a.r2"]
    assert _hits(first) == ["0.0.1-dev.a.r1", "0.0.1-dev.a.r2"]


def test_a_follower_writes_no_rows(tmp_path, pg_dsn, store, monkeypatch):
    uri, storage = store
    _save(storage, "0.0.1-dev.a.r1")
    leader = _replica(tmp_path, "leader", uri, pg_dsn, cache_dsn=pg_dsn)
    follower = _replica(tmp_path, "follower", uri, pg_dsn, cache_dsn=pg_dsn)
    assert leader.get(LIST).status_code == 200

    def no_write(*_a, **_k):
        raise AssertionError("a follower wrote search rows")

    monkeypatch.setattr(PgRowSearch, "sync", no_write)
    assert _hits(follower) == ["0.0.1-dev.a.r1"]


def test_search_requests_never_write_rows(tmp_path, pg_dsn, store, monkeypatch):
    uri, storage = store
    _save(storage, "0.0.1-dev.a.r1")
    written = PgRowSearch.sync

    def off_the_request_path(self, *args, **kwargs):
        assert threading.current_thread().name == "vmn-ui-refresh", "a request wrote rows"
        return written(self, *args, **kwargs)

    monkeypatch.setattr(PgRowSearch, "sync", off_the_request_path)
    client = _replica(tmp_path, "solo", uri, pg_dsn, background_refresh=True)
    try:
        until(lambda: _hits(client) == ["0.0.1-dev.a.r1"])
        _save(storage, "0.0.1-dev.a.r2")
        until(lambda: _hits(client) == ["0.0.1-dev.a.r1", "0.0.1-dev.a.r2"])
    finally:
        client.app.state.refresher.stop()


def test_a_single_replica_keeps_its_rows_current(tmp_path, pg_dsn, store):
    uri, storage = store
    _save(storage, "0.0.1-dev.a.r1")
    client = _replica(tmp_path, "solo", uri, pg_dsn)
    assert _hits(client) == ["0.0.1-dev.a.r1"]
    _save(storage, "0.0.1-dev.a.r2")
    assert _hits(client) == ["0.0.1-dev.a.r1", "0.0.1-dev.a.r2"]
