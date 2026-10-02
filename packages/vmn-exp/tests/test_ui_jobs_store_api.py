"""Store-workspace actions over HTTP: gated on the probed ``edit`` capability."""
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

APP = "my_app"
V = "0.0.1-dev.abc.def"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _setup(tmp_path, capabilities=None):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    if capabilities is not None:
        manager.set_capabilities("ws", capabilities)
    return TestClient(create_app(manager)), manager


def _wait(client, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_tag_on_a_store_workspace_is_visible_at_once(tmp_path):
    client, manager = _setup(tmp_path)
    r = client.post(f"{BASE}/actions/exp_tag", json={"verstr": V, "set": {"k": "v"}})
    assert r.status_code == 202, r.text
    job = _wait(client, r.json()["id"])
    assert job["status"] == "succeeded", job["log"]
    detail = client.get(f"{BASE}/experiments/{V}").json()
    assert [e["set"] for e in detail["log"] if e["type"] == "tags"] == [{"k": "v"}]
    assert "edit" in manager.get("ws").capabilities


def test_refused_without_the_edit_capability(tmp_path):
    client, _ = _setup(tmp_path, capabilities=["read"])
    r = client.post(f"{BASE}/actions/exp_tag", json={"verstr": V, "set": {"k": "v"}})
    assert r.status_code == 403
    assert "edit" in r.json()["detail"]


def test_git_actions_are_refused_on_a_store_workspace(tmp_path):
    client, _ = _setup(tmp_path, capabilities=["read", "edit"])
    r = client.post(f"{BASE}/actions/prune", json={"keep": 1})
    assert r.status_code == 400


def test_a_failed_read_probe_is_not_kept(tmp_path, monkeypatch):
    import vmn_exp.ui.storage_access as access
    from vmn_exp.ui.storage_access import Probe

    client, manager = _setup(tmp_path)
    monkeypatch.setattr(access, "probe_store",
                        lambda uri, **kw: Probe(warnings=["cannot read"]))
    r = client.post(f"{BASE}/actions/exp_tag", json={"verstr": V, "set": {"k": "v"}})
    assert r.status_code == 403
    assert manager.get("ws").capabilities is None
