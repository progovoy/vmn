"""Plan 28 P1 over HTTP: an app's attention queries (settings/conf
``experiment.ui.attention``) counted in ``experiments-status`` (``attention``,
``?scope=<v>`` for an outer run's page), per outer run on the Jobs view
(``job.attention``, ``sort=job:attention``), and ``ago()`` boards following
the clock."""
import datetime
import os

import pytest
import yaml

pytest.importorskip("fastapi")
import vmn_exp.core.status as status_mod
from fastapi.testclient import TestClient
from vmn_exp.core.app_settings_store import write_settings
from vmn_exp.storage.areas import RUNS
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.open import open_storage

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
T0 = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
SETTINGS = """\
ui:
  attention:
    - {key: unstable, query: 'tags.health = "unstable"', level: error}
    - {key: waiting, label: waiting over 1h, query: 'status = "created" and timestamp < ago("1h")'}
"""


def _v(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


def _iso(minutes):
    return (T0 + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(storage, n, minute, parent=None, state="ok", health=None):
    meta = {"verstr": _v(n), "timestamp": _iso(minute)}
    if parent is not None:
        meta["parent"] = _v(parent)
    storage.save(APP, _v(n), meta, {})
    if health:
        storage.append_log_entry(APP, _v(n), "w", {"timestamp": "t", "type": "tags",
                                                   "set": {"health": health}})
    states = {"ok": {"state": "finished", "exit_code": 0, "finished_at": _iso(minute + 1)},
              "failed": {"state": "finished", "exit_code": 1, "finished_at": _iso(minute + 1)},
              "live": {"state": "running", "started_at": _iso(minute), "heartbeat": _iso(90),
                       "heartbeat_interval_sec": 30}}
    if state in states:
        storage.save_file(APP, _v(n), "run_state.yml", yaml.dump(states[state]))


def _fleet(storage):
    """Outer r1 (running): r2 unstable, r3 waiting since minute 0, r4 waiting since 50,
    r5 failed. Outer r6: r7, r8 unstable. Single r9 unstable."""
    _run(storage, 1, 0, state="live")
    _run(storage, 2, 1, parent=1, health="unstable")
    _run(storage, 3, 0, parent=1, state=None)
    _run(storage, 4, 50, parent=1, state=None)
    _run(storage, 5, 2, parent=1, state="failed")
    _run(storage, 6, 3)
    _run(storage, 7, 4, parent=6, health="unstable")
    _run(storage, 8, 5, parent=6, health="unstable")
    _run(storage, 9, 6, health="unstable")


class _Clock:
    def __init__(self):
        self.now = T0 + datetime.timedelta(minutes=90)


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or c.now)
    return c


@pytest.fixture
def store(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    return (lambda: TestClient(create_app(manager))), storage


def _client(store, settings=SETTINGS):
    client_of, storage = store
    _fleet(storage)
    if settings:
        write_settings(storage, APP, settings)
    return client_of()


def _status(client, **params):
    r = client.get(f"{BASE}/experiments-status", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _counts(body):
    return {part["key"]: part["count"] for part in body["attention"]}


def test_the_status_counts_each_attention_query(store, clock):
    body = _status(_client(store))
    assert body["attention"] == [
        {"key": "unstable", "label": "unstable", "level": "error", "count": 4,
         "q": 'tags.health = "unstable"'},
        {"key": "waiting", "label": "waiting over 1h", "level": "warn", "count": 1,
         "q": 'status = "created" and timestamp < ago("1h")'},
    ]


def test_no_attention_queries_no_attention_field(store, clock):
    assert "attention" not in _status(_client(store, settings=None))


def test_an_ago_count_follows_the_clock(store, clock):
    client = _client(store)
    assert _counts(_status(client))["waiting"] == 1
    clock.now += datetime.timedelta(minutes=30)
    assert _counts(_status(client))["waiting"] == 2


def test_a_bad_query_is_reported_on_its_part(store, clock):
    bad = "ui:\n  attention:\n    - {key: typo, query: 'statuz = 1'}\n"
    body = _status(_client(store, settings=bad))
    part = body["attention"][0]
    assert part["count"] is None and "statuz" in part["error"]


def test_a_scope_counts_the_outer_runs_subtree(store, clock):
    body = _status(_client(store), scope=_v(1))
    assert body["total"] == 4
    assert body["counts"] == {"created": 2, "running": 0, "stuck": 0, "succeeded": 1,
                              "failed": 1}
    assert body["failed_recent"] == 1 and body["rollup"] == "failed"
    assert _counts(body) == {"unstable": 1, "waiting": 1}
    assert _counts(_status(_client(store), scope=_v(6))) == {"unstable": 2, "waiting": 0}


def test_a_leaf_scope_counts_nothing(store, clock):
    body = _status(_client(store), scope=_v(9))
    assert body["total"] == 0 and _counts(body) == {"unstable": 0, "waiting": 0}


def test_an_unknown_scope_is_404_and_a_bad_one_400(store, clock):
    client = _client(store)
    assert client.get(f"{BASE}/experiments-status", params={"scope": "nope"}).status_code == 404
    assert client.get(f"{BASE}/experiments-status", params={"scope": "a/../b"}).status_code == 400


def _jobs(client, **params):
    r = client.get(f"{BASE}/experiments", params={"top": "jobs", "limit": 50, **params})
    assert r.status_code == 200, r.text
    return r.json()["rows"]


def test_outer_runs_carry_their_attention_counts(store, clock):
    rows = {row["verstr"]: row["job"]["attention"] for row in _jobs(_client(store))}
    assert rows == {_v(1): {"unstable": 1, "waiting": 1}, _v(6): {"unstable": 2, "waiting": 0}}


def test_outer_runs_sort_by_attention_worst_first(store, clock):
    client = _client(store)
    assert [r["verstr"] for r in _jobs(client, sort="job:attention")] == [_v(6), _v(1)]
    assert [r["verstr"] for r in _jobs(client, sort="job:attention", order="asc")] == [
        _v(1), _v(6)]
    first = client.get(f"{BASE}/experiments", params={
        "top": "jobs", "limit": 1, "sort": "job:attention"}).json()
    after = client.get(f"{BASE}/experiments", params={
        "top": "jobs", "limit": 1, "sort": "job:attention",
        "cursor": first["next_cursor"]}).json()
    assert [first["rows"][0]["verstr"], after["rows"][0]["verstr"]] == [_v(6), _v(1)]


def test_without_attention_queries_jobs_carry_none(store, clock):
    assert all("attention" not in row["job"] for row in _jobs(_client(store, settings=None)))


def test_an_ago_board_follows_the_clock(store, clock):
    client = _client(store)
    q = 'status = "created" and timestamp < ago("1h")'

    def total():
        return client.get(f"{BASE}/experiments", params={"q": q, "limit": 10}).json()["total"]

    assert total() == 1
    clock.now += datetime.timedelta(minutes=30)
    assert total() == 2


def test_a_bad_ago_on_the_board_is_400(store, clock):
    client = _client(store)
    r = client.get(f"{BASE}/experiments", params={"q": 'timestamp < ago("1x")'})
    assert r.status_code == 400 and "ago()" in r.text


def test_a_checkout_conf_names_attention_queries_too(tmp_path, clock):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = LocalSnapshotStorage(str(root / ".vmn" / "store"), "runs")
    _fleet(storage)
    write_settings(storage, APP, SETTINGS)
    os.makedirs(root / ".vmn" / APP)
    attention = [{"key": "failing", "query": 'status = "failed"', "level": "error"}]
    with open(root / ".vmn" / APP / "conf.yml", "w") as f:
        yaml.dump({"conf": {"experiment": {"ui": {"attention": attention}}}}, f)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    assert _counts(_status(TestClient(create_app(manager)))) == {"failing": 1}
