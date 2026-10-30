"""Over HTTP, the stop/resume shape of a walk-forward launch: a resume opens
a new launch and the old one ends (failed) with its dates, studies and
trials never started. Those runs are ``settled = "never_started"``
(derived; their own status stays ``created``), so the old launch leaves the
Live preset and a waiting rule written with ``settled = null`` counts only
the new launch's runs; the running launch's created runs stay plain
``created`` and keep it live."""
import datetime
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.app_settings_store import write_settings  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
# The web's Live preset (webui/src/pages/Experiments/presets.ts) on the Outer runs view.
LIVE = ('depth = 0 and kind = "outer" and (status in ("running", "stuck") or '
        'tree_status in ("running", "created", "stuck") or live_below > 0)')
WAITING = 'status = "created" and settled = null and timestamp < ago("1h")'


def _v(n):
    return f"0.0.1-dev.{n:04d}abcd.{n}"


def _iso(sec_ago=0):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(seconds=sec_ago)).isoformat()


def _failed():
    return {"state": "finished", "exit_code": 1, "started_at": _iso(9000),
            "finished_at": _iso(7200)}


def _beating():
    return {"state": "running", "started_at": _iso(3600), "heartbeat": _iso(),
            "heartbeat_interval_sec": 30}


OLD, NEW = _v(1), _v(10)
# (n, parent n, run state): old launch -> date -> study -> 3 trials, all never
# started; new launch (running) -> date -> 2 trials, created.
RUNS_OF = [(1, None, _failed), (2, 1, None), (3, 2, None), (4, 3, None), (5, 3, None),
           (6, 3, None), (10, None, _beating), (11, 10, None), (12, 11, None), (13, 11, None)]
OLD_BELOW = {_v(n) for n in (2, 3, 4, 5, 6)}
NEW_BELOW = {_v(n) for n in (11, 12, 13)}


@pytest.fixture
def store(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for n, parent, state in RUNS_OF:
        meta = {"verstr": _v(n), "timestamp": "2026-01-01T00:00:00Z"}
        if parent:
            meta["parent"] = _v(parent)
        storage.save(APP, _v(n), meta, {})
        if state:
            storage.save_file(APP, _v(n), "run_state.yml", yaml.dump(state()))
    write_settings(storage, APP,
                   f"ui:\n  attention:\n    - {{key: waiting, query: '{WAITING}'}}\n")
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


def _get(client, path, **params):
    resp = client.get(f"{BASE}{path}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows(client, **params):
    return {r["verstr"]: r for r in _get(client, "/experiments", limit=50, **params)["rows"]}


def test_the_ended_launch_leaves_live_and_the_running_one_stays(store):
    rows = _rows(store, top=1, top_q=LIVE)
    assert set(rows) == {NEW}
    assert rows[NEW]["job"]["counts"]["waiting"] == 3


def test_the_ended_launchs_runs_never_started_and_the_running_ones_wait(store):
    rows = _rows(store)
    assert {(rows[v]["status"], rows[v]["settled"]) for v in OLD_BELOW} == {
        ("created", "never_started")}
    assert {(rows[v]["status"], rows[v]["settled"]) for v in NEW_BELOW} == {("created", None)}
    assert rows[OLD]["tree_status"] == "failed"


def test_the_settled_state_is_queryable(store):
    assert set(_rows(store, q='settled = "never_started"')) == OLD_BELOW
    assert set(_rows(store, q='status = "created" and settled = null')) == NEW_BELOW


def test_a_waiting_rule_with_settled_null_counts_the_running_launch_only(store):
    parts = _get(store, "/experiments-status")["attention"]
    assert [(p["key"], p["count"]) for p in parts] == [("waiting", 3)]
    jobs = _rows(store, top="jobs", sort="job:attention")
    assert jobs[NEW]["job"]["attention"] == {"waiting": 3}
    assert jobs[OLD]["job"]["attention"] == {"waiting": 0}
