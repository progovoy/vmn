"""Plan 31 §4.1/§4.2 over HTTP: ``status = "stuck" and settled != "lost"``
counts what ``experiments-status`` calls stuck; a query whose row-field
equality matches nothing while the value sits under ``tags.<field>`` or
``params.<field>`` answers a ``hints`` line; the web page's own URL params
are refused on ``.../experiments``."""
import datetime
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.writer import create_tags_entry  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
OUTER = "0.0.1-dev.0000abcd.0"
KIND_HINT = 'kind = "launch" matches nothing; did you mean tags.kind?'


def _iso(sec_ago=0):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(seconds=sec_ago)).isoformat()


FINISHED = {"state": "finished", "exit_code": 0, "started_at": _iso(7200),
            "finished_at": _iso(7000)}
STALE = {"state": "running", "started_at": _iso(7200), "heartbeat": _iso(7000),
         "heartbeat_interval_sec": 5}
# (state, parent, tags, params): an ended outer run, its lost child, a stuck
# top-level run, and a finished launch run with a host param.
RUNS_ = [(FINISHED, None, None, None), (STALE, OUTER, None, None), (STALE, None, None, None),
         (FINISHED, None, {"kind": "launch"}, {"host": "gpu1"})]


@pytest.fixture
def client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for i, (state, parent, tags, params) in enumerate(RUNS_):
        v = f"0.0.1-dev.{i:04d}abcd.{i}"
        meta = {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}
        if parent:
            meta["parent"] = parent
        storage.save(APP, v, meta, {})
        storage.save_file(APP, v, "run_state.yml", yaml.dump(state))
        if tags:
            storage.append_log_entry(APP, v, "w", create_tags_entry(tags))
        if params:
            storage.append_log_entry(APP, v, "w", {"timestamp": "t", "type": "params",
                                                   "params": params})
    old = datetime.datetime.now().timestamp() - 7000  # no fresh store write: stuck
    for root, _, files in os.walk(tmp_path / "store"):
        for name in files:
            os.utime(os.path.join(root, name), (old, old))
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


def _get(client, path, **params):
    if path == "/experiments":
        params.setdefault("limit", 50)  # a page, not the plain list
    resp = client.get(f"{BASE}{path}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_stuck_and_not_lost_counts_what_experiments_status_calls_stuck(client):
    status = _get(client, "/experiments-status")
    assert (status["counts"]["stuck"], status["lost"]) == (1, 1)
    plain = _get(client, "/experiments", q='status = "stuck"')
    assert plain["total"] == 2  # the lost child keeps its own status
    settled = _get(client, "/experiments", q='status = "stuck" and settled != "lost"')
    assert settled["total"] == status["counts"]["stuck"]


def test_a_row_field_matching_nothing_hints_at_the_tag(client):
    body = _get(client, "/experiments", q='kind = "launch"')
    assert body["rows"] == [] and body["hints"] == [KIND_HINT]


def test_the_hint_reads_equalities_inside_an_and(client):
    body = _get(client, "/experiments", q='status = "succeeded" and kind = "launch"')
    assert body["hints"] == [KIND_HINT]


def test_a_row_field_matching_nothing_hints_at_the_param(client):
    body = _get(client, "/experiments", q='host = "gpu1"')
    assert body["hints"] == ['host = "gpu1" matches nothing; did you mean params.host?']


@pytest.mark.parametrize("q", ['kind = "nowhere"', 'not kind = "launch" and kind = "x"',
                               'tags.kind = "nope"'])
def test_no_hint_without_the_value_under_a_tag_or_param(client, q):
    body = _get(client, "/experiments", q=q)
    assert body["rows"] == [] and "hints" not in body


def test_no_hint_when_rows_match(client):
    body = _get(client, "/experiments", q='kind = "launch" or status = "succeeded"')
    assert body["rows"] and "hints" not in body


def test_jobs_view_and_grouped_pages_carry_the_hint(client):
    assert _get(client, "/experiments", q='kind = "launch"', top="1")["hints"] == [KIND_HINT]
    grouped = _get(client, "/experiments", q='kind = "launch"', group="parent")
    assert grouped["groups"] == [] and grouped["hints"] == [KIND_HINT]
    assert "hints" not in _get(client, "/experiments", q='tags.kind = "launch"', group="parent")


@pytest.mark.parametrize("name", ["view", "kind", "tab", "sel"])
def test_web_page_params_are_refused(client, name):
    resp = client.get(f"{BASE}/experiments", params={name: "jobs"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == f"{name} is a web page parameter; use top=jobs or q=…"
