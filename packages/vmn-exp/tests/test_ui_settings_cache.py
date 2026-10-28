"""Plan 28 A0: the server's cache of apps' store settings re-reads them
after its window, or at once when the journal says they changed."""
from vmn_exp.core.app_settings import parse_settings
from vmn_exp.core.app_settings_store import write_settings
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.settings_cache import SettingsCache

APP = "root_app/svc"
TEXT = "metrics: {loss: {goal: min}}\nui: {group_aggregate: best}\n"


def _store(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), "runs")


def test_the_cache_rereads_after_its_window_or_when_told(tmp_path):
    storage, now = _store(tmp_path), [0.0]
    cache = SettingsCache(recheck_sec=60, clock=lambda: now[0])
    write_settings(storage, APP, "ui: {stale_after_min: 1}\n")
    assert cache.get("ws", storage, APP) == {"ui": {"stale_after_min": 1}}
    write_settings(storage, APP, "ui: {stale_after_min: 2}\n")
    assert cache.get("ws", storage, APP)["ui"]["stale_after_min"] == 1
    cache.forget("ws", "root_app-svc")
    assert cache.get("ws", storage, APP)["ui"]["stale_after_min"] == 2
    write_settings(storage, APP, "ui: {stale_after_min: 3}\n")
    now[0] = 61.0
    assert cache.get("ws", storage, APP)["ui"]["stale_after_min"] == 3


def test_a_zero_window_cache_reads_every_time(tmp_path):
    storage = _store(tmp_path)
    cache = SettingsCache(recheck_sec=0)
    assert cache.get("ws", storage, APP) == {}
    write_settings(storage, APP, TEXT)
    assert cache.get("ws", storage, APP) == parse_settings(TEXT)
