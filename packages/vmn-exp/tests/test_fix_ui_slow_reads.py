"""Slow per-run storage reads never starve the index-snapshot routes.

Run detail, the batch series, logs, patches and media read records from the
store (seconds to minutes on S3). They run on their own bounded capacity, so
a leaderboard list still answers while every such reader is blocked.
"""
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
BLOCKED = 48  # more than the default 40-thread pool


def _client(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = open_storage(root=local_store_root(str(root)), area="runs")
    storage.save(APP, "1.0.0-dev.a", {"verstr": "1.0.0-dev.a",
                                      "timestamp": "2026-01-01T00:00:00Z"}, {})

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager))


def _blocking(release, entered):
    def stub(*args, **kwargs):
        entered.append(1)
        release.wait(30)
        raise RuntimeError("released")
    return stub


def _block_series(monkeypatch, stub):
    from vmn_exp.ui import routes_series

    monkeypatch.setattr(routes_series, "batch_series", stub)
    return lambda c: c.post(f"{BASE}/series", json={"verstrs": ["1.0.0-dev.a"]})


def _block_detail(monkeypatch, stub):
    from vmn_exp.ui.readers import experiments as exp_reader

    monkeypatch.setattr(exp_reader, "get_experiment_from_storage", stub)
    return lambda c: c.get(f"{BASE}/experiments/1.0.0-dev.a")


def _call_quietly(request, client):
    try:
        request(client)
    except Exception:
        pass


@pytest.mark.parametrize("block", [_block_series, _block_detail], ids=["series", "detail"])
def test_list_answers_while_slow_readers_are_blocked(tmp_path, monkeypatch, block):
    release, entered = threading.Event(), []
    request = block(monkeypatch, _blocking(release, entered))
    with _client(tmp_path) as client:
        assert client.get(f"{BASE}/experiments").status_code == 200  # warm the index
        slow = [threading.Thread(target=_call_quietly, args=(request, client), daemon=True)
                for _ in range(BLOCKED)]
        try:
            for t in slow:
                t.start()
            deadline = time.monotonic() + 10
            while len(entered) < 8 and time.monotonic() < deadline:
                time.sleep(0.02)
            time.sleep(0.5)  # let the rest take whatever threads they can
            answered = []
            lister = threading.Thread(
                target=lambda: answered.append(client.get(f"{BASE}/experiments").status_code),
                daemon=True,
            )
            lister.start()
            lister.join(5)
            assert answered == [200], f"list waited behind {len(entered)} blocked readers"
        finally:
            release.set()
            for t in slow:
                t.join(30)
