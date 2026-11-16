"""Store-workspace actions over HTTP: gated on the probed ``edit`` capability."""
import os
import threading

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from job_wait import wait_job_http  # noqa: E402

from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.core.real_io import RealClock, real_io

APP = "my_app"
V = "0.0.1-dev.abc.def"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _setup(tmp_path, capabilities=None):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS, clock=RealClock(), env=os.environ)
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(os.path.join(tmp_path, "ui_data"))
    manager.add_store("ws", uri)
    if capabilities is not None:
        manager.set_capabilities("ws", capabilities)
    return TestClient(create_app(manager, io=real_io())), manager


_wait = wait_job_http


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


class _HangingStorage:
    """The edit storage with every call held until *gate* is set (at most 5 s,
    so code that calls the store inline fails here instead of hanging)."""

    def __init__(self, storage, gate, entered):
        self._storage, self._gate, self._entered = storage, gate, entered

    def __getattr__(self, name):
        attr = getattr(self._storage, name)
        if not callable(attr):
            return attr

        def held(*args, **kwargs):
            self._entered.set()
            self._gate.wait(5)
            return attr(*args, **kwargs)

        return held


def test_a_store_action_request_returns_while_the_store_hangs(tmp_path, monkeypatch):
    import vmn_exp.storage.open as storage_open

    gate, entered = threading.Event(), threading.Event()
    real_open = storage_open.open_storage

    def open_edit_storage(uri, **kwargs):
        storage = real_open(uri, **kwargs)
        return _HangingStorage(storage, gate, entered) if kwargs.get("buffer_logs") else storage

    monkeypatch.setattr(storage_open, "open_storage", open_edit_storage)
    client, _ = _setup(tmp_path, capabilities=["read", "edit"])
    try:
        r = client.post(f"{BASE}/actions/exp_tag", json={"verstr": V, "set": {"k": "v"}})
        assert r.status_code == 202, r.text
        assert r.json()["status"] == "running"
        assert entered.wait(5) and not gate.is_set()
        assert client.get(f"/api/v1/jobs/{r.json()['id']}").json()["status"] == "running"
    finally:
        gate.set()
    assert _wait(client, r.json()["id"])["status"] == "succeeded"


class _StuckUpload:
    """The edit storage holding an earlier edit whose upload keeps failing."""

    def __init__(self, storage):
        self._storage = storage

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def has_pending(self):
        return True

    def ship_pending(self):
        raise ConnectionError("the store is out of reach")


def stuck_edit_storage(monkeypatch):
    """Make the UI server's edit storage a :class:`_StuckUpload`."""
    import vmn_exp.storage.open as storage_open

    real_open = storage_open.open_storage

    def open_edit_storage(uri, **kwargs):
        storage = real_open(uri, **kwargs)
        return _StuckUpload(storage) if kwargs.get("buffer_logs") else storage

    monkeypatch.setattr(storage_open, "open_storage", open_edit_storage)


def test_a_store_action_first_retries_an_earlier_pending_edit(tmp_path, monkeypatch):
    stuck_edit_storage(monkeypatch)
    client, _ = _setup(tmp_path, capabilities=["read", "edit"])
    r = client.post(f"{BASE}/actions/exp_tag", json={"verstr": V, "set": {"k": "v"}})
    job = _wait(client, r.json()["id"])
    assert job["status"] == "failed"
    assert "An earlier edit is still pending" in job["log"]
    detail = client.get(f"{BASE}/experiments/{V}").json()
    assert not [e for e in detail["log"] if e["type"] == "tags"]
