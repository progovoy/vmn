"""Plan 28 T2b over HTTP: a run still beating under an ended outer run is
``settled = "outlived"``. It counts as running everywhere, and a built-in
``outlived`` attention part (level warn) counts it in ``experiments-status``
and per outer run (``job.attention``) — only while there is one, configured
queries or not."""
import datetime
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.app_settings import SettingsError, parse_settings  # noqa: E402
from vmn_exp.core.app_settings_store import write_settings  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
PART = {"key": "outlived", "label": "outlived their outer run", "level": "warn", "count": 1,
        "q": 'settled = "outlived"'}


def _v(n):
    return f"0.0.1-dev.{n:04d}abcd.{n}"


ENDED, ORPHAN, OPEN, OPEN_KID = _v(1), _v(2), _v(4), _v(5)


def _iso(sec_ago=0):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(seconds=sec_ago)).isoformat()


def _beating():
    return {"state": "running", "started_at": _iso(3600), "heartbeat": _iso(),
            "heartbeat_interval_sec": 30}


def _finished():
    return {"state": "finished", "exit_code": 0, "started_at": _iso(7200),
            "finished_at": _iso(3000)}


# Outer r1 ended: r2 still beating, r3 done. Outer r4 running: r5 running.
RUNS_OF = [(1, None, _finished), (2, 1, _beating), (3, 1, _finished),
           (4, None, _beating), (5, 4, _beating)]


@pytest.fixture
def store(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for n, parent, state in RUNS_OF:
        meta = {"verstr": _v(n), "timestamp": f"2026-01-01T00:00:{n:02d}Z"}
        if parent:
            meta["parent"] = _v(parent)
        storage.save(APP, _v(n), meta, {})
        storage.save_file(APP, _v(n), "run_state.yml", yaml.dump(state()))
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return storage, lambda: TestClient(create_app(manager))


def _get(client, path, **params):
    resp = client.get(f"{BASE}{path}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_status_counts_it_running_and_names_it(store):
    body = _get(store[1](), "/experiments-status")
    assert body["counts"]["running"] == 3 and "lost" in body and body["lost"] == 0
    assert body["attention"] == [PART]


def test_the_built_in_part_comes_before_configured_ones(store):
    storage, client_of = store
    write_settings(storage, APP, "ui:\n  attention:\n    - {key: all, query: 'idx > 0'}\n")
    keys = [p["key"] for p in _get(client_of(), "/experiments-status")["attention"]]
    assert keys == ["outlived", "all"]


def test_a_scope_counts_its_own_subtree(store):
    client = store[1]()
    assert _get(client, "/experiments-status", scope=ENDED)["attention"] == [PART]
    assert "attention" not in _get(client, "/experiments-status", scope=OPEN)


def test_outer_runs_carry_it_and_rank_first(store):
    rows = _get(store[1](), "/experiments", top="jobs", limit=10, sort="job:attention")["rows"]
    assert [r["verstr"] for r in rows] == [ENDED, OPEN]
    assert rows[0]["job"]["attention"] == {"outlived": 1}
    assert rows[0]["job"]["counts"]["running"] == 1
    assert "attention" not in rows[1]["job"]


def test_the_board_and_the_run_detail_name_it(store):
    client = store[1]()
    rows = _get(client, "/experiments", limit=10, q='settled = "outlived"')["rows"]
    assert [(r["verstr"], r["status"]) for r in rows] == [(ORPHAN, "running")]
    assert _get(client, f"/experiments/{ORPHAN}")["status"]["settled"] == "outlived"
    summary = _get(client, f"/experiments/{ENDED}/summary")
    assert summary["counts"]["running"] == 1 and summary["lost"] == 0


def test_nothing_outlived_no_attention_field(store):
    storage, client_of = store
    storage.save_file(APP, ORPHAN, "run_state.yml", yaml.dump(_finished()))
    assert "attention" not in _get(client_of(), "/experiments-status")
    rows = _get(client_of(), "/experiments", top="jobs", limit=10)["rows"]
    assert all("attention" not in r["job"] for r in rows)


def test_outlived_is_a_built_in_attention_key():
    with pytest.raises(SettingsError, match="outlived"):
        parse_settings("ui:\n  attention:\n    - {key: outlived, query: 'idx > 0'}\n")
