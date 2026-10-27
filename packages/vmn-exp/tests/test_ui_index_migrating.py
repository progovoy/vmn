"""A server whose index file an upgrade left to re-derive keeps answering:
``/apps`` and the status routes never wait for the re-derive, which reports
itself as the freshness phase ``migrating`` (with its progress) until the
persisted rows are back; the cache health check re-derives an older derived
version in the background instead of rebuilding the cache from storage."""
import os
import sqlite3
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core import index_derive, index_store_schema, sqlite_files  # noqa: E402
from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.core.index_store import SqliteStore  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui import index as ui_index  # noqa: E402
from vmn_exp.ui.cache_health import SqliteHealth  # noqa: E402
from vmn_exp.ui.cache_resync import WorkspaceCache  # noqa: E402

APP = "my_app"
API = "/api/v1/workspaces/ws"
STATUS = f"{API}/apps/{APP}/experiments-status"
OLDER = f"exp-index-{index_store_schema.DERIVED_VERSION - 1}"
FINISHED = "state: finished\nexit_code: 0\n"


def _seed(tmp_path, n=3):
    uri = f"file://{tmp_path}/store"
    st = open_storage(uri, area=RUNS)
    for i in range(n):
        v = f"0.0.1-dev.0000abcd.{i}"
        st.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        st.save_file(APP, v, "run_state.yml", FINISHED)
    return uri, st


def _older_derived(db):
    conn = sqlite3.connect(sqlite_files.live_path(db))
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'schema'", (OLDER,))
    conn.commit()
    conn.close()


def _get_in_time(client, url, timeout=5.0):
    """*url*'s JSON, failing the test when the route does not answer in time."""
    answer = []
    thread = threading.Thread(target=lambda: answer.append(client.get(url)), daemon=True)
    thread.start()
    thread.join(timeout)
    assert answer, f"{url} did not answer within {timeout}s"
    assert answer[0].status_code == 200, answer[0].text
    return answer[0].json()


def _until(fetch, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    body = fetch()
    while not predicate(body) and time.monotonic() < deadline:
        time.sleep(0.05)
        body = fetch()
    return body


@pytest.fixture
def held_derive(monkeypatch):
    """Every re-derive chunk waits for ``.set()``."""
    release, real = threading.Event(), index_derive.derive_chunk

    def slow(*args, **kwargs):
        release.wait(20)
        return real(*args, **kwargs)

    monkeypatch.setattr(index_derive, "derive_chunk", slow)
    yield release
    release.set()


def _slow_app_listing(*args):
    time.sleep(30)  # listing 486k run names on S3
    return True


def test_apps_and_status_answer_while_the_index_rederives(tmp_path, held_derive, monkeypatch):
    from vmn_exp.ui import server
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    monkeypatch.setattr(server, "app_exists", _slow_app_listing)

    uri, st = _seed(tmp_path)
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    db = ui_index.s3_cache_path(os.path.join(tmp_path, "ui_data", "index"), manager.get("ws"))
    ExperimentIndex(st, APP, db).refresh()
    _older_derived(db)

    app = create_app(manager, background_refresh=True)
    client = TestClient(app)
    try:
        body = _until(lambda: _get_in_time(client, STATUS),
                      lambda b: (b.get("freshness") or {}).get("phase") == "migrating")
        assert body["freshness"]["phase"] == "migrating"
        assert body["freshness"]["progress"] == 0
        assert [a["name"] for a in _get_in_time(client, f"{API}/apps")] == [APP]
        assert _get_in_time(client, f"{API}/apps-status")[APP]["freshness"]["phase"] == "migrating"

        held_derive.set()
        body = _until(lambda: _get_in_time(client, STATUS), lambda b: b["total"] == 3)
        assert body["total"] == 3
        assert body["freshness"]["phase"] != "migrating"
    finally:
        app.state.refresher.stop()


def test_the_health_check_rederives_an_older_derived_version_in_place(tmp_path):
    uri, st = _seed(tmp_path)
    db = str(tmp_path / "cache.sqlite")
    ExperimentIndex(st, APP, db).refresh()
    _older_derived(db)
    cache = WorkspaceCache("ws", db, SqliteHealth(db), check_sec=0)
    cache.note(APP, st, lambda: None)

    assert cache.tick() == "derived"
    assert cache.wait(10)
    assert cache.rebuilds == 0 and not cache.rebuilding
    assert sqlite_files.live_path(db) == db  # no new generation: nothing rebuilt
    store = SqliteStore(db)
    assert not store.deriving(APP) and store.count(APP) == 3
    assert cache.tick() is None
