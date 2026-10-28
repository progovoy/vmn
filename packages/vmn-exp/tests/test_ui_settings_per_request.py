"""Plan 28 A0 follow-up: an inline-refresh server reads an app's store
settings once per request, however many read paths ask for them."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.app_settings_store import write_settings  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui import settings_cache  # noqa: E402
from vmn_exp.ui.settings_cache import SettingsCache, request_scope  # noqa: E402

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


@pytest.fixture
def reads(monkeypatch):
    """The settings reads made, as app names."""
    made, read = [], settings_cache.read_settings

    def counted(storage, app_name):
        made.append(app_name)
        return read(storage, app_name)

    monkeypatch.setattr(settings_cache, "read_settings", counted)
    return made


def _client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    verstr = "0.0.1-dev.abc1234.def5678.r1"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:01Z"}, {})
    storage.save_file(APP, verstr, "run_state.yml", "state: finished\nexit_code: 0\n")
    write_settings(storage, APP, "metrics: {loss: {goal: min}}\nui: {group_aggregate: min}\n")
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


def test_an_inline_refresh_request_reads_the_settings_once(tmp_path, reads):
    client = _client(tmp_path)
    for params in [{}, {"group": "parent", "sort": "loss"}]:
        client.get(f"{BASE}/experiments", params=params)  # warm the index
        reads.clear()
        assert client.get(f"{BASE}/experiments", params=params).status_code == 200
        assert reads == [APP]


def test_a_zero_window_cache_reads_once_per_request_scope(tmp_path, reads):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    cache = SettingsCache(recheck_sec=0)
    with request_scope():
        cache.get("ws", storage, APP)
        write_settings(storage, APP, "ui: {stale_after_min: 2}\n")
        assert cache.get("ws", storage, APP) == {}
        cache.forget("ws", APP)
        assert cache.get("ws", storage, APP) == {"ui": {"stale_after_min": 2}}
    with request_scope():
        cache.get("ws", storage, APP)
    cache.get("ws", storage, APP)
    cache.get("ws", storage, APP)
    assert len(reads) == 5


def test_a_windowed_cache_ignores_request_scopes(tmp_path, reads):
    storage, now = LocalSnapshotStorage(str(tmp_path / "store"), "runs"), [0.0]
    cache = SettingsCache(recheck_sec=60, clock=lambda: now[0])
    with request_scope():
        cache.get("ws", storage, APP)
        now[0] = 61.0
        cache.get("ws", storage, APP)
    assert len(reads) == 2
