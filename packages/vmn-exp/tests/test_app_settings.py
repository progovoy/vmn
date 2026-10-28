"""Plan 28 A0: an app's settings in the store's ``settings/`` area — the
reader-facing subset of conf's ``experiment:`` block, parsed, validated,
stored, journaled and read below a checkout's conf."""
import pytest

from vmn_exp.core.app_settings import (
    SettingsError,
    metrics_overlay,
    parse_settings,
    ui_overlay,
)
from vmn_exp.core.app_settings_store import (
    SettingsCache,
    read_settings,
    read_settings_text,
    write_settings,
)
from vmn_exp.core.journal_keys import decode_key
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.journal import journaled
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "root_app/svc"
TEXT = """\
# team defaults
metrics:
  loss: {goal: min, primary: true}
  "grad_*": {hidden: true}
  acc: {summary: max, step_metric: epoch}
ui:
  group_aggregate: best
  stale_after_min: 30
  attention: [{key: waiting, query: "status = created"}]
"""


def _store(tmp_path, sink=None):
    local = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    return journaled(local, sink=sink, writer_id="host", backoff=lambda a: None) if sink else local


class RecordingSink:
    def __init__(self):
        self.keys = []

    def put(self, key):
        self.keys.append(key)


def test_parse_keeps_known_keys_and_unknown_ui_keys():
    settings = parse_settings(TEXT)
    assert settings["metrics"]["loss"] == {"goal": "min", "primary": True}
    assert settings["metrics"]["grad_*"] == {"hidden": True}
    assert settings["ui"]["group_aggregate"] == "best"
    assert settings["ui"]["attention"] == [{"key": "waiting", "query": "status = created"}]


@pytest.mark.parametrize("text", ["", "   \n", "# nothing\n"])
def test_an_empty_file_is_no_settings(text):
    assert parse_settings(text) == {}


@pytest.mark.parametrize("text, words", [
    ("- a\n- b\n", "mapping"),
    ("storage: {uri: s3://x}\n", "storage"),
    ("metrics: [loss]\n", "metrics"),
    ("metrics: {loss: {goal: up}}\n", "goal"),
    ("metrics: {loss: {summary: none}}\n", "summary"),
    ("metrics: {loss: {hidden: 'yes'}}\n", "hidden"),
    ("metrics: {loss: {primary: 1}}\n", "primary"),
    ("metrics: {loss: {step_metric: 3}}\n", "step_metric"),
    ("metrics: {loss: {colour: red}}\n", "colour"),
    ("metrics: {a: {primary: true}, b: {primary: true}}\n", "primary"),
    ("ui: [x]\n", "ui"),
    ("ui: {group_aggregate: sum}\n", "group_aggregate"),
    ("ui: {stale_after_min: 0}\n", "stale_after_min"),
    ("ui: {stale_after_min: true}\n", "stale_after_min"),
    ("metrics: {loss: [\n", "YAML"),
])
def test_invalid_settings_are_refused_naming_the_key(text, words):
    with pytest.raises(SettingsError, match=words):
        parse_settings(text)


def test_conf_beats_settings_per_metric_and_per_ui_key():
    settings = parse_settings(TEXT)
    merged = metrics_overlay(settings, {"loss": {"goal": "max"}})
    assert merged["loss"] == {"goal": "max"}
    assert merged["grad_*"] == {"hidden": True}
    ui = ui_overlay(settings, {"group_aggregate": "min"})
    assert ui["group_aggregate"] == "min" and ui["stale_after_min"] == 30
    assert metrics_overlay({}, None) == {} and ui_overlay({}, None) == {}


def test_settings_round_trip_keeps_the_text(tmp_path):
    storage = _store(tmp_path)
    assert read_settings(storage, APP) == {} and read_settings_text(storage, APP) is None
    write_settings(storage, APP, TEXT, actor={"name": "ann"})
    assert read_settings_text(storage, APP) == TEXT
    assert read_settings(storage, APP) == parse_settings(TEXT)
    write_settings(storage, APP, "ui: {group_aggregate: min}\n")
    assert read_settings(storage, APP) == {"ui": {"group_aggregate": "min"}}


def test_settings_live_in_the_settings_area(tmp_path):
    write_settings(_store(tmp_path), APP, TEXT)
    path = tmp_path / "store" / "settings" / "root_app-svc" / "app" / "experiment.yml"
    assert path.read_text() == TEXT


def test_an_invalid_write_changes_nothing(tmp_path):
    storage = _store(tmp_path)
    write_settings(storage, APP, TEXT)
    with pytest.raises(SettingsError):
        write_settings(storage, APP, "ui: {group_aggregate: sum}\n")
    assert read_settings_text(storage, APP) == TEXT


def test_a_broken_stored_file_reads_as_no_settings(tmp_path):
    storage = _store(tmp_path)
    write_settings(storage, APP, TEXT)
    (tmp_path / "store" / "settings" / "root_app-svc" / "app" / "experiment.yml").write_text(
        "metrics: [\n")
    assert read_settings(storage, APP) == {}


def test_a_write_puts_a_settings_journal_entry(tmp_path):
    sink = RecordingSink()
    write_settings(_store(tmp_path, sink), APP, TEXT)
    scopes = {(k.area, k.app_key) for k in map(decode_key, sink.keys)}
    assert scopes == {("settings", "root_app-svc")}


def test_a_local_first_storage_reads_and_writes_the_remote(tmp_path):
    remote = LocalSnapshotStorage(str(tmp_path / "remote"), "runs")
    cached = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "local"), "runs"), remote)
    write_settings(cached, APP, TEXT)
    assert read_settings_text(remote, APP) == TEXT
    write_settings(remote, APP, "ui: {stale_after_min: 9}\n")  # another host
    assert read_settings(cached, APP) == {"ui": {"stale_after_min": 9}}


def test_the_cache_rereads_after_its_window_or_when_told(tmp_path):
    storage, now = _store(tmp_path), [0.0]
    cache = SettingsCache(recheck_sec=60, clock=lambda: now[0])
    write_settings(storage, APP, "ui: {stale_after_min: 1}\n")
    assert cache.get(("ws", APP), storage, APP) == {"ui": {"stale_after_min": 1}}
    write_settings(storage, APP, "ui: {stale_after_min: 2}\n")
    assert cache.get(("ws", APP), storage, APP)["ui"]["stale_after_min"] == 1
    cache.forget("ws", "root_app-svc")
    assert cache.get(("ws", APP), storage, APP)["ui"]["stale_after_min"] == 2
    write_settings(storage, APP, "ui: {stale_after_min: 3}\n")
    now[0] = 61.0
    assert cache.get(("ws", APP), storage, APP)["ui"]["stale_after_min"] == 3


def test_a_root_holding_settings_is_not_taken_for_a_v1_store(tmp_path):
    from vmn_exp.storage.store_marker import forget_checked, require_store

    write_settings(_store(tmp_path), APP, TEXT)
    forget_checked()
    require_store(_store(tmp_path))


def test_a_zero_window_cache_reads_every_time(tmp_path):
    storage = _store(tmp_path)
    cache = SettingsCache(recheck_sec=0)
    assert cache.get(("ws", APP), storage, APP) == {}
    write_settings(storage, APP, TEXT)
    assert cache.get(("ws", APP), storage, APP) == parse_settings(TEXT)
