"""Routes that resolve run refs answer ``{"detail", "code"}``: run_not_found
-> 404, ambiguous_ref -> 409, invalid_ref -> 400 (the message unchanged)."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
VERSTRS = ("0.0.1-dev.aaaa1111.1", "0.0.1-dev.aaaa2222.2")
AMBIGUOUS = "Ambiguous prefix '0.0.1-dev.aaaa': matches 2 experiments: " + ", ".join(VERSTRS)


def _client(tmp_path, verstrs=VERSTRS):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    for i, v in enumerate(verstrs):
        storage.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    return TestClient(create_app(manager))


@pytest.fixture
def client(tmp_path):
    return _client(tmp_path)


CASES = [
    ("0.0.1-dev.zzzz", 404, "run_not_found", "Experiment '0.0.1-dev.zzzz' not found"),
    ("0.0.1-dev.aaaa", 409, "ambiguous_ref", AMBIGUOUS),
    ("@9", 404, "run_not_found", "Index '@9' out of range (1..2)"),
    ("@x", 400, "invalid_ref", "Invalid index reference '@x' (use @N, e.g. @1)"),
    ("9.9.9", 404, "run_not_found", "Experiment 9.9.9 not found"),
]


def _assert_error(r, status, code, message):
    assert r.status_code == status, r.text
    assert r.json() == {"detail": message, "code": code}


@pytest.mark.parametrize("ref,status,code,message", CASES)
def test_run_detail(client, ref, status, code, message):
    _assert_error(client.get(f"{BASE}/experiments/{ref}"), status, code, message)


@pytest.mark.parametrize("ref,status,code,message", CASES)
def test_run_log(client, ref, status, code, message):
    _assert_error(client.get(f"{BASE}/experiments/{ref}/log"), status, code, message)


@pytest.mark.parametrize("ref,status,code,message", CASES)
def test_diff_either_side(client, ref, status, code, message):
    for v, to in ((ref, VERSTRS[0]), (VERSTRS[0], ref)):
        r = client.get(f"{BASE}/experiments-diff", params={"v": v, "to": to})
        _assert_error(r, status, code, message)


def test_latest_without_runs_is_run_not_found(tmp_path):
    client = _client(tmp_path, VERSTRS[:1])
    r = client.get("/api/v1/workspaces/ws/apps/other_app/experiments/latest")
    _assert_error(r, 404, "run_not_found", "No experiments found for other_app")


def test_a_resolved_ref_still_answers(client):
    assert client.get(f"{BASE}/experiments/@1", params={"series": "false"}).status_code == 200
