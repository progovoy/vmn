"""The UI composition root (plan 44 G4): ``build_app(manager, deps)`` serves
with the collaborators it is given, ``real_deps(io, ...)`` builds the real
ones from the given IO, and ``create_app`` requires that IO."""
import argparse

import pytest
from fastapi.testclient import TestClient

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from vmn_exp.core import writer
from vmn_exp.core.ports import IO
from vmn_exp.storage.open import open_storage
from vmn_exp.ui.app_deps import ServerDeps, real_deps
from vmn_exp.ui.cli import server_app
from vmn_exp.ui.control_plane import SQLiteControlPlane
from vmn_exp.ui.jobs import JobRunner
from vmn_exp.ui.refresher import InlineRefresher, Refresher
from vmn_exp.ui.server import build_app, create_app
from vmn_exp.ui.store_upkeep import StoreUpkeep
from vmn_exp.ui.workspaces import WorkspaceManager
from vmn_exp.core.real_io import RealClock

RUN = "0.0.1-dev.a"
SERVER = dict(control_plane=None, background_refresh=False, read_only=False, keep_warm=None)


def _io():
    return IO(clock=FakeClock(), env=FakeEnv(), processes=FakeProcesses(),
              random=FakeRandom(), host=FakeHost(), console=FakeConsole())


def _manager(tmp_path):
    store = tmp_path / "store"
    open_storage(root=str(store), area="runs", clock=RealClock()).save(
        "app", RUN, {"verstr": RUN, "timestamp": "2026-01-01T00:00:00Z"}, {})
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("st", f"file://{store}")
    return manager


def _deps(**changes):
    deps = real_deps(_io(), **SERVER)
    return ServerDeps(**{**deps.__dict__, **changes})


class RecordingRunner(JobRunner):
    def __init__(self):
        super().__init__(processes=FakeProcesses(), random=FakeRandom(), start_thread=None)
        self.submitted = []

    def submit_call(self, ws, command, call):
        self.submitted.append((ws, command))
        return {"id": "j", "command": command, "status": "running"}, None


class RecordingRefresher(InlineRefresher):
    def __init__(self):
        super().__init__()
        self.indexes = []

    def snapshot(self, index, journal=None):
        self.indexes.append(index)
        return super().snapshot(index, journal)


def test_build_app_uses_the_given_job_runner(tmp_path):
    runner = RecordingRunner()
    client = TestClient(build_app(_manager(tmp_path), _deps(jobs=runner)))

    resp = client.post("/api/v1/workspaces/st/apps/app/actions/note",
                       json={"verstr": RUN, "note": "hi"})

    assert resp.status_code == 202, resp.text
    assert [ws for ws, _ in runner.submitted] == ["st"]


def test_build_app_uses_the_given_refresher(tmp_path):
    refresher = RecordingRefresher()
    client = TestClient(build_app(_manager(tmp_path), _deps(refresher=refresher)))

    resp = client.get("/api/v1/workspaces/st/apps/app/metrics-schema")

    assert resp.status_code == 200, resp.text
    assert refresher.indexes


def test_build_app_without_control_plane_has_no_audit_or_token_service(tmp_path):
    deps = real_deps(_io(), **SERVER)
    app = build_app(_manager(tmp_path), deps)

    assert deps.audit is None and deps.token_service is None
    assert app.state.audit is None


def test_real_deps_gives_audit_and_tokens_the_io_wall_clock(tmp_path):
    io = _io()
    deps = real_deps(io, **{**SERVER, "control_plane": SQLiteControlPlane(str(tmp_path / "cp.db"))})

    io.clock.advance(5)

    assert deps.audit.clock() == io.clock.now().timestamp()
    assert deps.token_service.clock() == io.clock.now().timestamp()


def test_real_deps_gives_the_refresher_the_io_monotonic_clock():
    io = _io()
    deps = real_deps(io, **{**SERVER, "background_refresh": True})

    io.clock.advance(7)

    assert deps.refresher._clock() == io.clock.monotonic()


def test_create_app_wires_a_background_refresher_only_when_asked(tmp_path):
    manager = _manager(tmp_path)

    assert isinstance(create_app(manager, io=_io()).state.refresher, InlineRefresher)
    assert isinstance(create_app(manager, io=_io(), background_refresh=True).state.refresher,
                      Refresher)


def test_create_app_requires_its_io(tmp_path):
    with pytest.raises(TypeError, match="io"):
        create_app(_manager(tmp_path))


def test_server_app_builds_on_the_given_io(tmp_path, monkeypatch):
    monkeypatch.setattr(writer, "_WRITER_ID", writer._WRITER_ID)  # server_app sets it
    io = _io()
    args = argparse.Namespace(host="127.0.0.1", read_only=False, no_index=False,
                              allowed_host=None)
    app = server_app(_manager(tmp_path), None, SQLiteControlPlane(str(tmp_path / "cp.db")),
                     args, io=io)

    io.clock.advance(3)

    assert app.state.audit.clock() == io.clock.now().timestamp()


@pytest.mark.parametrize("background_refresh, read_only, built", [
    (True, False, True),
    (True, True, False),
    (False, False, False),
])
def test_real_deps_builds_upkeep_only_for_background_writable_servers(
        background_refresh, read_only, built):
    deps = real_deps(_io(), **{**SERVER, "background_refresh": background_refresh,
                               "read_only": read_only})

    assert isinstance(deps.upkeep, StoreUpkeep) is built
    assert (deps.upkeep is None) is not built
