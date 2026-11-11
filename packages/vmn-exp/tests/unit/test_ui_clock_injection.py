"""The UI's classes read time from the clock their builder hands them, never
from a real-clock default (plan 44 G19): epoch seconds for the audit log,
tokens, sessions, the control-plane sweep and the change journal; monotonic
seconds for the caches, the upkeep, the refresher and the registry snapshots."""
import inspect
import threading
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from vmn_exp.core.app_settings_store import write_settings
from vmn_exp.core.ports import IO
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui import live_events, routes_events
from vmn_exp.ui.app_deps import ServerDeps, real_deps
from vmn_exp.ui.audit import AuditLog, audit_key
from vmn_exp.ui.auth.oidc import OIDCAuthenticator
from vmn_exp.ui.auth.principal import Principal
from vmn_exp.ui.auth.sessions import SessionService
from vmn_exp.ui.auth.tokens import TokenService
from vmn_exp.ui.cache_resync import WorkspaceCache
from vmn_exp.ui.control_plane import SQLiteControlPlane
from vmn_exp.ui.control_plane_sweep import ControlPlaneSweeper, install
from vmn_exp.ui.experiment_source import ExperimentSource
from vmn_exp.ui.failure_streak import FailureStreak
from vmn_exp.ui.journal_follow import WorkspaceJournal
from vmn_exp.ui.refresher import Refresher
from vmn_exp.ui.registry_snapshot import REFRESH_SEC, RegistryListings, RegistrySnapshots
from vmn_exp.ui.server import build_app
from vmn_exp.ui.settings_cache import SettingsCache
from vmn_exp.ui.store_upkeep import AppUpkeep, StoreUpkeep
from vmn_exp.ui.workspaces import WorkspaceManager

APP = "app"
SERVER = dict(background_refresh=False, read_only=False, keep_warm=None)


def _io(clock):
    return IO(clock=clock, env=FakeEnv(), processes=FakeProcesses(),
              random=FakeRandom(), host=FakeHost(), console=FakeConsole())


def _cp(tmp_path):
    return SQLiteControlPlane(str(tmp_path / "cp.db"))


def _wall(clock):
    return lambda: clock.now().timestamp()


@pytest.mark.parametrize("taker, param", [
    (AuditLog, "clock"), (TokenService, "clock"), (SessionService, "clock"),
    (OIDCAuthenticator, "clock"), (ControlPlaneSweeper, "clock"), (FailureStreak, "clock"),
    (Refresher, "clock"), (SettingsCache, "clock"), (WorkspaceCache, "clock"),
    (WorkspaceJournal, "clock"), (AppUpkeep, "clock"), (StoreUpkeep, "clock"),
    (RegistrySnapshots, "clock"), (RegistryListings, "clock"), (ExperimentSource, "clock"),
    (live_events.event_stream, "clock"), (live_events.event_stream, "sleep"),
])
def test_ui_clock_takers_have_no_real_default(taker, param):
    assert inspect.signature(taker).parameters[param].default is inspect.Parameter.empty


def test_audit_entry_timestamp_comes_from_the_clock(tmp_path):
    clock = FakeClock()
    audit = real_deps(_io(clock), control_plane=_cp(tmp_path), **SERVER).audit

    clock.advance(42)

    assert audit.record("u1", "login")["ts"] == clock.now().timestamp()


def test_api_token_created_at_comes_from_the_clock(tmp_path):
    clock = FakeClock()
    tokens = real_deps(_io(clock), control_plane=_cp(tmp_path), **SERVER).token_service

    _, record = tokens.create("ci", {}, ttl_sec=60)

    assert record.created_at == clock.now().timestamp()
    assert record.expires_at == clock.now().timestamp() + 60


class RecordingTokens(TokenService):
    listed = 0

    def list(self):
        self.listed += 1
        return super().list()


def test_admin_routes_use_the_app_token_service(tmp_path):
    clock, cp = FakeClock(), _cp(tmp_path)
    deps = real_deps(_io(clock), control_plane=cp, **SERVER)
    tokens = RecordingTokens(cp, clock=_wall(clock))
    deps = ServerDeps(**{**deps.__dict__, "token_service": tokens})
    secret, _ = tokens.create("admin", {"*": "admin"})
    client = TestClient(build_app(WorkspaceManager(str(tmp_path / "data")), deps,
                                  control_plane=cp))

    resp = client.get("/api/v1/tokens", headers={"Authorization": f"Bearer {secret}"})

    assert resp.status_code == 200, resp.text
    assert tokens.listed == 1


def test_session_expires_when_the_fake_clock_passes_the_ttl(tmp_path):
    clock = FakeClock()
    sessions = SessionService(_cp(tmp_path), clock=_wall(clock), ttl_sec=60)
    session_id = sessions.open(Principal("oidc:a", "a", {}))

    clock.advance(59)
    assert sessions.principal(session_id) is not None
    clock.advance(2)
    assert sessions.principal(session_id) is None


class BackgroundRefresher:
    background, interval_sec = True, 1

    def add_listener(self, listener):
        pass


def _source(tmp_path, clock):
    return ExperimentSource(str(tmp_path / "data"), refresher=BackgroundRefresher(), clock=clock)


def test_settings_are_rechecked_after_recheck_sec_on_the_given_clock(tmp_path):
    clock = FakeClock()
    source, ws = _source(tmp_path, clock), types.SimpleNamespace(name="ws", kind="s3")
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    write_settings(storage, APP, "ui: {stale_after_min: 1}\n", actor="t")
    source.app_settings(ws, APP, storage)
    write_settings(storage, APP, "ui: {stale_after_min: 2}\n", actor="t")

    clock.advance(59)
    assert source.app_settings(ws, APP, storage)["ui"]["stale_after_min"] == 1
    clock.advance(2)
    assert source.app_settings(ws, APP, storage)["ui"]["stale_after_min"] == 2


def test_experiment_source_gives_its_caches_monotonic_and_its_journal_wall_time(tmp_path):
    clock = FakeClock()
    source, ws = _source(tmp_path, clock), types.SimpleNamespace(name="ws", kind="s3")
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    cache_path = str(tmp_path / "cache.db")

    cache, journal = source.cache(ws, cache_path), source._journal(ws, storage, cache_path)
    clock.advance(9)

    assert cache._clock() == clock.monotonic()
    assert journal._clock() == clock.now().timestamp()


class _Index:
    leading = False  # a pass returns at once


def test_store_upkeep_spaces_its_passes_on_the_given_clock_and_hands_it_to_app_upkeep():
    clock, index = FakeClock(), _Index()
    upkeep = StoreUpkeep(interval_sec=10, clock=clock.monotonic)
    upkeep.note(index, None, APP)
    try:
        upkeep.refreshed(index, "first")
        assert upkeep.wait_idle(5)
        upkeep.refreshed(index, "second")
        assert not upkeep.wait_idle(0)  # not due inside the interval
        clock.advance(10)
        upkeep.refreshed(index, "third")
        assert upkeep.wait_idle(5)
    finally:
        upkeep.stop()
    assert upkeep._apps[index]._clock == clock.monotonic


class RecordingCp:
    def __init__(self):
        self.calls = []

    def sweep_expired(self, now):
        self.calls.append(("sessions", now))

    def delete_keys_below(self, kind, bound):
        self.calls.append((kind, bound))


def test_control_plane_sweep_cutoff_follows_the_given_clock():
    clock, store = FakeClock(), RecordingCp()
    sweeper = install(FastAPI(), store, 30, _wall(clock))
    now = clock.now().timestamp()

    sweeper.sweep()

    assert store.calls == [("sessions", now), ("audit", audit_key(now - 30 * 86400))]


def test_build_app_sweeps_the_control_plane_on_the_io_wall_clock(tmp_path):
    clock, cp = FakeClock(), _cp(tmp_path)
    deps = real_deps(_io(clock), control_plane=cp, **SERVER)
    app = build_app(WorkspaceManager(str(tmp_path / "data")), deps, control_plane=cp)

    clock.advance(5)

    assert app.state.sweeper.clock() == clock.now().timestamp()


class AsyncClock:
    def __init__(self):
        self.clock = FakeClock()

    def monotonic(self):
        return self.clock.monotonic()

    async def sleep(self, sec):
        self.clock.advance(sec)


def test_event_stream_heartbeats_on_the_given_clock_without_real_sleeping():
    clock, app = AsyncClock(), FastAPI()
    started = clock.monotonic()
    snapshot = types.SimpleNamespace(generation=1, run_states={}, rows=[])
    routes_events.register(app, "/api", lambda ws, tag: lambda: snapshot, True,
                           lambda value, what: value, clock.monotonic, clock.sleep)

    body = TestClient(app).get("/api/workspaces/ws/apps/app/events").text

    assert "event: hello" in body
    assert clock.monotonic() - started >= live_events.MAX_STREAM_SEC


class Counting:
    def __init__(self):
        self.reads = 0

    def __call__(self, storage, previous, listing):
        self.reads += 1
        return self.reads


class _Storage:
    pass


def test_registry_snapshot_is_rebuilt_only_after_refresh_sec_on_the_given_clock():
    clock, read, storage = FakeClock(), Counting(), _Storage()
    snapshots = RegistrySnapshots(True, read, clock=clock.monotonic)

    assert snapshots.get(storage) == 1
    clock.advance(REFRESH_SEC - 1)
    assert snapshots.get(storage) == 1 and read.reads == 1
    clock.advance(1)
    snapshots.get(storage)  # starts the refresh on a thread
    for thread in threading.enumerate():
        if thread.name == "vmn-ui-registry":
            thread.join(5)
    assert read.reads == 2


def test_registry_listing_is_reused_inside_refresh_sec_on_the_given_clock(tmp_path):
    clock = FakeClock()
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    listings = RegistryListings(clock=clock.monotonic)

    at, _ = listings.get(storage)
    assert at == clock.monotonic()
    clock.advance(REFRESH_SEC - 1)
    assert listings.get(storage)[0] == at
    clock.advance(1)
    assert listings.get(storage)[0] == clock.monotonic()
