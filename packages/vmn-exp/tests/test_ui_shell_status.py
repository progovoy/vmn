"""GET .../experiments-status: the status counts behind the shell's rollup
(plan 19 §2.1, §1.9), over the leaderboard's non-archived rows."""
import datetime
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import vmn_exp.core.status as status_mod  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.status_summary import status_summary  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
STATUSES = ("created", "running", "stuck", "succeeded", "failed")


class _Clock:
    def __init__(self):
        self.now = datetime.datetime.now(datetime.timezone.utc)

    def iso(self, sec_ago=0):
        return (self.now - datetime.timedelta(seconds=sec_ago)).isoformat()

    def advance(self, sec):
        self.now += datetime.timedelta(seconds=sec)


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or c.now)
    return c


def _finished(clock, code, sec_ago):
    return {"state": "finished", "exit_code": code, "started_at": clock.iso(sec_ago + 10),
            "finished_at": clock.iso(sec_ago)}


def _running(clock):
    return {"state": "running", "started_at": clock.iso(), "heartbeat": clock.iso(),
            "heartbeat_interval_sec": 5}


def _setup(tmp_path, runs):
    """*runs*: ``[(run_state or None, archived)]``, oldest first."""
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for i, (state, archived) in enumerate(runs):
        v = f"0.0.1-dev.{i:04d}abcd.{i}"
        meta = {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z", "archived": archived}
        storage.save(APP, v, meta, {})
        if state is not None:
            storage.save_file(APP, v, "run_state.yml", yaml.dump(state))
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


def _status(client, app=APP):
    r = client.get(f"/api/v1/workspaces/ws/apps/{app}/experiments-status")
    assert r.status_code == 200, r.text
    return r.json()


def _fleet(clock):
    return [
        (None, False),                       # created
        (_running(clock), False),            # running
        (_finished(clock, 0, 100), False),   # succeeded
        (_finished(clock, 0, 50), False),    # succeeded
        (_finished(clock, 1, 3600), False),  # failed, recent
        (_finished(clock, 1, 3 * 86400), False),  # failed, old
        (_finished(clock, 1, 10), True),     # archived: not counted
    ]


def test_counts_over_non_archived_rows(tmp_path, clock):
    body = _status(_setup(tmp_path, _fleet(clock)))
    assert body == {
        "total": 6,
        "counts": {"created": 1, "running": 1, "stuck": 0, "succeeded": 2, "failed": 2},
        "failed_recent": 1, "recent_sec": 86400, "rollup": "failed",
    }


def test_counts_match_the_leaderboard_status_filter(tmp_path, clock):
    client = _setup(tmp_path, _fleet(clock))
    counts = _status(client)["counts"]
    for s in ("running", "stuck", "failed"):
        page = client.get(f"{BASE}/experiments", params={"status": s, "limit": 1}).json()
        assert counts[s] == page["total"], s


def test_failed_recent_ages_out_on_the_hour(tmp_path, clock):
    client = _setup(tmp_path, [(_finished(clock, 1, 86400 - 1800), False)])
    assert _status(client)["failed_recent"] == 1
    clock.advance(3600)
    body = _status(client)
    assert body["failed_recent"] == 0
    assert body["counts"]["failed"] == 1
    assert body["rollup"] is None


def test_a_live_run_turns_stuck_across_buckets(tmp_path, clock):
    client = _setup(tmp_path, [(_running(clock), False)])
    assert _status(client)["rollup"] == "running"
    clock.advance(600)
    body = _status(client)
    assert body["counts"]["running"] == 0 and body["counts"]["stuck"] == 1
    assert body["rollup"] == "stuck"


def test_etag_and_304(tmp_path, clock):
    client = _setup(tmp_path, _fleet(clock))
    r = client.get(f"{BASE}/experiments-status")
    etag = r.headers["ETag"]
    again = client.get(f"{BASE}/experiments-status", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_unknown_app_is_all_zeros(tmp_path, clock):
    body = _status(_setup(tmp_path, _fleet(clock)), app="nope")
    assert body["total"] == 0
    assert body["counts"] == dict.fromkeys(STATUSES, 0)
    assert body["failed_recent"] == 0 and body["rollup"] is None


def test_invalid_tag_is_400(tmp_path, clock):
    client = _setup(tmp_path, [])
    assert client.get("/api/v1/workspaces/ws/apps/x-../experiments-status").status_code == 400


def _row(status, finished_at=None):
    return {"status": status, "finished_at": finished_at}


@pytest.mark.parametrize("rows,rollup", [
    ([_row("stuck"), _row("failed", "2026-01-01T23:00:00Z"), _row("running")], "stuck"),
    ([_row("failed", "2026-01-01T23:00:00Z"), _row("running")], "failed"),
    ([_row("failed", "2025-12-01T00:00:00Z"), _row("running")], "running"),
    ([_row("succeeded"), _row("created")], None),
])
def test_rollup_precedence(rows, rollup):
    now = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    assert status_summary(rows, now)["rollup"] == rollup


def test_summary_always_has_every_status():
    now = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    body = status_summary([], now)
    assert body == {"total": 0, "counts": dict.fromkeys(STATUSES, 0),
                    "failed_recent": 0, "recent_sec": 86400, "rollup": None}
