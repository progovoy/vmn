"""The first open of a 100k-run app waited ~6s: the index load, then the
board's base built on the request. ``vmn-exp ui`` now warms every app's board
at startup and after each background refresh, off the request path, so the
first page answers from a built base."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from leaderboard_fleet import T0, Fleet
from test_fix_ui_list_serving import BASE, _app, _run
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache

SCHEMA = {"loss": {"goal": "min", "primary": True}}


def _count_base_builds(monkeypatch):
    built = []
    for name in ("build", "derived"):
        real = getattr(leaderboard_cache._Base, name)
        monkeypatch.setattr(leaderboard_cache._Base, name, classmethod(
            lambda cls, *a, _real=real, **k: built.append(1) or _real.__func__(cls, *a, **k)))
    return built


def test_a_warmed_snapshot_serves_its_first_page_without_building(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet, cache = Fleet(1), LeaderboardCache()
    fleet.seed(500, T0, sweeps=2, live=5)
    snap = fleet.snapshot()

    cache.warm(snap)
    built = _count_base_builds(monkeypatch)
    cache.page(snap, SCHEMA, sort="loss", limit=50)

    assert built == []


def test_the_server_warms_its_apps_at_startup(tmp_path, monkeypatch):
    app, storage = _app(tmp_path, background_refresh=True)
    for i in range(20):
        _run(storage, i, loss=i / 10)
    try:
        with TestClient(app) as client:
            assert app.state.warmed.wait(30)
            built = _count_base_builds(monkeypatch)

            page = client.get(f"{BASE}/experiments?limit=50")

            assert page.status_code == 200 and page.json()["total"] == 20
            assert built == []
    finally:
        app.state.refresher.stop()
