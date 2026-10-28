"""Plan 28 N6 over HTTP: ``experiments?children_of=<v>`` pages a run's
direct children, each with children carrying its ``job`` (attention from
the app's settings, its split counts), an ``open`` hint, and the app's
``tree_columns``; ETag/304 like the board, 404/400 for unknown/malformed."""
import datetime

import pytest
import yaml

pytest.importorskip("fastapi")
import vmn_exp.core.status as status_mod
from fastapi.testclient import TestClient
from vmn_exp.core.app_settings_store import write_settings
from vmn_exp.storage.areas import RUNS
from vmn_exp.storage.open import open_storage

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
T0 = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
SETTINGS = """\
ui:
  split_by: tags.kind
  attention:
    - {key: unstable, query: 'tags.health = "unstable"', level: error}
  tree_columns:
    date: [c:duration, m:loss]
"""


def _v(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


def _iso(minutes):
    return (T0 + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(storage, n, minute, parent=None, state="ok", **tags):
    meta = {"verstr": _v(n), "timestamp": _iso(minute)}
    if parent is not None:
        meta["parent"] = _v(parent)
    storage.save(APP, _v(n), meta, {})
    if tags:
        storage.append_log_entry(APP, _v(n), "w", {"timestamp": "t", "type": "tags", "set": tags})
    states = {"ok": {"state": "finished", "exit_code": 0, "finished_at": _iso(minute + 1)},
              "live": {"state": "running", "started_at": _iso(minute), "heartbeat": _iso(90),
                       "heartbeat_interval_sec": 30}}
    storage.save_file(APP, _v(n), "run_state.yml", yaml.dump(states[state]))


def _tree(storage):
    """Launch r1 (live): date r2 (live: r3 ok, r4 live), date r5 (r6 unstable, r7 ok), leaf r8."""
    _run(storage, 1, 0, state="live")
    _run(storage, 2, 1, parent=1, state="live", kind="date")
    _run(storage, 3, 2, parent=2, kind="trial")
    _run(storage, 4, 3, parent=2, state="live", kind="trial")
    _run(storage, 5, 4, parent=1, kind="date")
    _run(storage, 6, 5, parent=5, kind="trial", health="unstable")
    _run(storage, 7, 6, parent=5, kind="refit")
    _run(storage, 8, 7, parent=1)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    monkeypatch.setattr(status_mod, "_now",
                        lambda now=None: now or T0 + datetime.timedelta(minutes=90))
    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    _tree(storage)
    write_settings(storage, APP, SETTINGS)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    test_client = TestClient(create_app(manager))
    test_client.storage = storage
    return test_client


def _children(client, parent, **params):
    r = client.get(f"{BASE}/experiments", params={"children_of": parent, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _rows(body):
    return {row["verstr"]: row for row in body["rows"]}


def test_children_of_serves_the_direct_children_with_their_jobs(client):
    body = _children(client, _v(1))
    rows = _rows(body)
    assert set(rows) == {_v(2), _v(5), _v(8)} and body["total"] == 3
    assert body["next_cursor"] is None
    assert body["tree_columns"] == {"date": ["c:duration", "m:loss"]}
    assert rows[_v(2)]["job"]["total"] == 2
    assert rows[_v(5)]["job"]["attention"] == {"unstable": 1}
    assert rows[_v(2)]["job"]["attention"] == {"unstable": 0}
    assert rows[_v(8)]["job"] is None


def test_open_marks_live_and_unhealthy_nodes(client):
    rows = _rows(_children(client, _v(1)))
    assert {v for v, row in rows.items() if row["open"]} == {_v(2), _v(5)}


def test_a_leaf_carries_its_own_attention(client):
    rows = _rows(_children(client, _v(5)))
    assert rows[_v(6)]["attention"] == {"unstable": 1}
    assert "attention" not in rows[_v(7)]


def test_each_job_carries_the_apps_split(client):
    job = _rows(_children(client, _v(1)))[_v(5)]["job"]
    assert job["split"] == "tags.kind"
    assert {entry["key"]: entry["total"] for entry in job["by"]} == {"refit": 1, "trial": 1}


def test_children_page_filter_sort_and_cursor(client):
    assert set(_rows(_children(client, _v(2), status="running"))) == {_v(4)}
    assert set(_rows(_children(client, _v(1), q='tags.kind = "date"'))) == {_v(2), _v(5)}
    assert _children(client, _v(1), q='timestamp < ago("1h")')["total"] == 3
    first = _children(client, _v(1), limit=2, sort="job:attention")
    assert first["rows"][0]["verstr"] == _v(5)
    rest = _children(client, _v(1), limit=2, sort="job:attention", cursor=first["next_cursor"])
    assert [row["verstr"] for row in rest["rows"]] == [
        v for v in (_v(2), _v(8)) if v not in _rows(first)]


def test_a_new_child_shows_up_and_moves_the_etag(client):
    r = client.get(f"{BASE}/experiments", params={"children_of": _v(2)})
    etag = r.headers["etag"]
    again = client.get(f"{BASE}/experiments", params={"children_of": _v(2)},
                       headers={"If-None-Match": etag})
    assert again.status_code == 304
    _run(client.storage, 9, 8, parent=2)
    fresh = client.get(f"{BASE}/experiments", params={"children_of": _v(2)},
                       headers={"If-None-Match": etag})
    assert fresh.status_code == 200 and _v(9) in _rows(fresh.json())


def test_an_unknown_run_is_404(client):
    r = client.get(f"{BASE}/experiments", params={"children_of": _v(99)})
    assert r.status_code == 404


@pytest.mark.parametrize("params", [
    {"children_of": ".."},
    {"children_of": _v(1), "group": "status"},
    {"children_of": _v(1), "top": "1"},
    {"children_of": _v(1), "top": "1", "match_subtree": "1"},
    {"children_of": _v(1), "q": "comments > 0"},
])
def test_malformed_or_combined_children_of_is_400(client, params):
    assert client.get(f"{BASE}/experiments", params=params).status_code == 400
