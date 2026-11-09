"""Run detail marks a metric whose steps went back without a rewind
(``step_restarts``) and still shows its last write as the value."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"
VERSTR = "1.0.0-dev.a"


def _ts(i):
    return f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}.000000Z"


def _metric(i, step, value):
    return {"timestamp": _ts(i), "type": "metrics", "step": step,
            "values": {"study.best_so_far": value}}


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = open_storage(root=local_store_root(str(root)), area="runs")
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": _ts(0)}, {})
    storage.append_log_entry(APP, VERSTR, "w", {"timestamp": _ts(0), "type": "create"})

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager)), storage


def _log(storage, entries):
    for entry in entries:
        storage.append_log_entry(APP, VERSTR, "w", entry)


def _detail(client):
    r = client.get(f"{BASE}/{VERSTR}")
    assert r.status_code == 200
    return r.json()


def test_a_restarted_step_counter_is_marked_and_the_last_write_shown(ws):
    client, storage = ws
    _log(storage, [_metric(i + 1, i, 0.954 if i == 120 else 0.5) for i in range(121)])
    _log(storage, [_metric(200 + i, i, 0.989 if i == 5 else 0.98) for i in range(6)])
    detail = _detail(client)
    assert detail["metrics"]["study.best_so_far"] == 0.989
    assert detail["step_restarts"] == {
        "study.best_so_far": {"write": 122, "from": 120, "to": 0},
    }


def test_monotone_steps_carry_no_marker(ws):
    client, storage = ws
    _log(storage, [_metric(i + 1, i, 0.5) for i in range(10)])
    assert "step_restarts" not in _detail(client)


def test_a_rewind_is_not_a_restart(ws):
    client, storage = ws
    _log(storage, [_metric(i + 1, i, 0.5) for i in range(10)])
    _log(storage, [{"timestamp": _ts(20), "type": "rewind", "step": 4}])
    _log(storage, [_metric(21 + i, 5 + i, 0.7) for i in range(3)])
    assert "step_restarts" not in _detail(client)


def test_a_restart_logged_after_a_poll_is_marked(ws):
    client, storage = ws
    _log(storage, [_metric(i + 1, i, 0.5) for i in range(10)])
    assert "step_restarts" not in _detail(client)
    _log(storage, [_metric(30, 2, 0.9)])
    assert _detail(client)["step_restarts"] == {
        "study.best_so_far": {"write": 11, "from": 9, "to": 2},
    }
