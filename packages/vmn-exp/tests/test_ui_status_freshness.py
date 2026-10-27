"""An app's experiments-status (and apps-status) says how fresh the index it
serves is (``freshness``): when its data dates from (``as_of``, which
survives a restart), whether a refresh runs and how far it is, and whether
the refresh is failing or stuck, so the dashboard can warn about stale data;
an inline refresher reports none."""
import datetime
import os
import threading
import time

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import vmn_exp.core.index_freshness as freshness_module  # noqa: E402
from vmn_exp.core.index import ExperimentIndex  # noqa: E402
from vmn_exp.core.index_sweep import Sweep  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.freshness import STUCK_REFRESH_SEC, freshness, freshness_key  # noqa: E402

APP = "my_app"
STATUS = f"/api/v1/workspaces/ws/apps/{APP}/experiments-status"
KEYS = {"as_of", "refreshing", "refresh_running_sec", "phase", "progress", "refresh_failing",
        "last_error", "stale_after_sec"}
OCT_22 = 1792698240.0  # 2026-10-22T19:44:00Z
HEALTHY = {"alive": True, "failing": False, "failures": 0, "since_refresh_sec": 0.5,
           "refreshing_sec": None, "last_error": None}
IDLE = {"as_of": OCT_22, "refreshing": False, "phase": "idle", "progress": None}


def _seed(tmp_path):
    uri = f"file://{tmp_path}/store"
    v = "0.0.1-dev.0000abcd.0"
    open_storage(uri, area=RUNS).save(APP, v, {"verstr": v, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return uri


def _client(tmp_path, background_refresh=True):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = _seed(tmp_path)
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    if "ws" not in {w.name for w in manager.list()}:
        manager.add_store("ws", uri)
    app = create_app(manager, background_refresh=background_refresh)
    return app, TestClient(app)


@pytest.fixture
def background(tmp_path):
    app, client = _client(tmp_path)
    yield client
    app.state.refresher.stop()


def _wait_for_status(client, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    body = client.get(STATUS).json()
    while not predicate(body.get("freshness") or {}) and time.monotonic() < deadline:
        time.sleep(0.05)
        body = client.get(STATUS).json()
    return body


def _iso(wall):
    return datetime.datetime.fromtimestamp(wall, datetime.timezone.utc).isoformat()


def test_a_fresh_idle_index_reports_when_its_data_is_from(background):
    before = time.time()
    body = _wait_for_status(background, lambda f: f.get("as_of") and not f["refreshing"])
    fresh = body["freshness"]
    assert set(fresh) == KEYS
    as_of = datetime.datetime.fromisoformat(fresh["as_of"]).timestamp()
    assert before - 5 <= as_of <= time.time()
    assert fresh["phase"] == "idle" and fresh["progress"] is None
    assert fresh["refresh_running_sec"] is None
    assert not fresh["refresh_failing"] and fresh["last_error"] is None
    assert fresh["stale_after_sec"] == 300


def test_a_failing_refresh_is_reported(background, monkeypatch):
    background.get(STATUS)

    def broken(self):
        raise RuntimeError("storage went away")

    monkeypatch.setattr(ExperimentIndex, "refresh", broken)
    body = _wait_for_status(background, lambda f: f.get("refresh_failing"))
    assert body["freshness"]["refresh_failing"]
    assert "storage went away" in body["freshness"]["last_error"]


def test_apps_status_carries_each_apps_freshness(background):
    background.get(STATUS)
    body = background.get("/api/v1/workspaces/ws/apps-status").json()
    assert set(body[APP]["freshness"]) == KEYS


def test_an_inline_refresher_reports_no_freshness(tmp_path):
    _, client = _client(tmp_path, background_refresh=False)
    assert "freshness" not in client.get(STATUS).json()


def test_a_restarted_server_serves_its_persisted_data_as_of_its_last_refresh(
        tmp_path, monkeypatch):
    monkeypatch.setattr(freshness_module, "_wall", lambda: OCT_22)
    app, client = _client(tmp_path)
    _wait_for_status(client, lambda f: f.get("as_of") and not f["refreshing"])
    app.state.refresher.stop()

    monkeypatch.setattr(freshness_module, "_wall", time.time)
    gate, real = threading.Event(), Sweep.listing

    def held(self, records, now):  # a refresh that takes long on the old data
        gate.wait(10)
        return real(self, records, now)

    monkeypatch.setattr(Sweep, "listing", held)
    app, client = _client(tmp_path)
    try:
        body = _wait_for_status(client, lambda f: f.get("refreshing"))
        fresh = body["freshness"]
        assert fresh["as_of"] == _iso(OCT_22)
        assert fresh["refreshing"] and not fresh["refresh_failing"]
        assert fresh["phase"] in ("full_listing", "journal", "listing")
    finally:
        gate.set()
        app.state.refresher.stop()


def test_an_idle_fresh_payload():
    assert freshness(HEALTHY, IDLE) == {
        "as_of": _iso(OCT_22), "refreshing": False, "refresh_running_sec": None,
        "phase": "idle", "progress": None, "refresh_failing": False, "last_error": None,
        "stale_after_sec": 300,
    }


def test_a_refresh_on_an_old_snapshot_says_how_far_it_is():
    health = dict(HEALTHY, since_refresh_sec=None, refreshing_sec=125.4)
    state = dict(IDLE, refreshing=True, phase="full_listing", progress=0.45)
    fresh = freshness(health, state, stale_after_min=10)
    assert fresh["refreshing"] and fresh["refresh_running_sec"] == 125
    assert fresh["phase"] == "full_listing" and fresh["progress"] == 0.45
    assert not fresh["refresh_failing"] and fresh["stale_after_sec"] == 600


def test_a_refresh_past_the_timeout_counts_as_failing():
    health = dict(HEALTHY, refreshing_sec=STUCK_REFRESH_SEC + 1)
    state = dict(IDLE, refreshing=True, phase="full_listing", progress=0.1)
    fresh = freshness(health, state)
    assert fresh["refresh_failing"] and fresh["last_error"] is None
    assert not freshness(dict(HEALTHY, refreshing_sec=STUCK_REFRESH_SEC - 1), state)[
        "refresh_failing"]


def test_a_failing_or_dead_refresher_counts_as_failing():
    failing = dict(HEALTHY, failing=True, failures=3, last_error="OSError('reset')")
    assert freshness(failing, IDLE)["refresh_failing"]
    assert freshness(failing, IDLE)["last_error"] == "OSError('reset')"
    assert freshness(dict(HEALTHY, alive=False), IDLE)["refresh_failing"]


def test_the_etag_key_moves_by_the_minute():
    now = OCT_22 + 3600  # stale
    one = freshness(HEALTHY, IDLE)
    assert freshness_key(one, now) == freshness_key(
        freshness(HEALTHY, dict(IDLE, as_of=OCT_22 + 30)), now)
    assert freshness_key(one, now) != freshness_key(
        freshness(HEALTHY, dict(IDLE, as_of=OCT_22 + 60)), now)
    running = [freshness(dict(HEALTHY, refreshing_sec=s), dict(IDLE, refreshing=True))
               for s in (61, 100, 125)]
    keys = [freshness_key(f, now) for f in running]
    assert keys[0] == keys[1] != keys[2]
    assert freshness_key(None, now) is None


def test_a_fresh_indexs_refreshes_leave_the_etag_key_alone():
    now = OCT_22 + 10
    idle = freshness_key(freshness(HEALTHY, IDLE), now)
    listing = freshness(dict(HEALTHY, refreshing_sec=0.5),
                        dict(IDLE, refreshing=True, phase="journal"))
    assert freshness_key(listing, now) == idle
    assert freshness_key(listing, OCT_22 + 3600) != freshness_key(
        freshness(HEALTHY, IDLE), OCT_22 + 3600)


def test_the_stale_threshold_comes_from_the_apps_conf(tmp_path):
    from vmn_exp.ui.readers.experiments import stale_after_min

    root = str(tmp_path)
    assert stale_after_min(root, APP) == 5
    os.makedirs(os.path.join(root, ".vmn", APP))
    for value, expected in ((30, 30), (0, 5), ("x", 5)):
        with open(os.path.join(root, ".vmn", APP, "conf.yml"), "w") as f:
            yaml.dump({"conf": {"experiment": {"ui": {"stale_after_min": value}}}}, f)
        assert stale_after_min(root, APP) == expected
