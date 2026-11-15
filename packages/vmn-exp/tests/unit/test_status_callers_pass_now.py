"""Status callers take their time from the clock they are given (plan 44
G11): the board's cache reads its ``now`` once per build or time bucket, a
snapshot answers at the ``now`` asked, and ``vmn-exp list`` derives at the
handler's clock. No module clock is patched."""
import argparse
from datetime import datetime, timezone

import pytest

from fastapi.testclient import TestClient

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from leaderboard_fleet import Fleet, running
from similar_seed import seed, verstr
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.cli import experiment
from vmn_exp.core.ports import IO
from vmn_exp.core.status import RUNNING, STUCK
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.app_deps import ServerDeps, real_deps
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.server import build_app
from vmn_exp.ui.store_upkeep import AppUpkeep
from vmn_exp.ui.workspaces import WorkspaceManager

APP = "app"
# Later than any store write time a test leaves, so the heartbeat decides.
LATER = datetime(2099, 1, 1, tzinfo=timezone.utc)
HOUR = 3600


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


def _statuses(cache, snapshot):
    return {row["verstr"]: row["status"] for row in cache.rows(snapshot)}


def _live_fleet(clock):
    fleet = Fleet()
    return fleet, fleet.append(state=running(clock.now()))


def test_leaderboard_rows_flip_to_stuck_when_the_fake_clock_advances():
    clock = FakeClock()
    fleet, live = _live_fleet(clock)
    cache, snapshot = LeaderboardCache(now=clock.now), fleet.snapshot()
    assert _statuses(cache, snapshot)[live] == RUNNING

    clock.advance(HOUR)

    assert _statuses(cache, snapshot)[live] == STUCK


def test_now_is_read_per_snapshot_build_not_once_per_refresher():
    clock = FakeClock()
    fleet, live = _live_fleet(clock)
    reads = []

    def now():
        reads.append(clock.now())
        return clock.now()

    cache = LeaderboardCache(now=now)
    assert _statuses(cache, fleet.snapshot())[live] == RUNNING
    clock.advance(HOUR)
    fleet.append()

    assert _statuses(cache, fleet.snapshot())[live] == STUCK
    assert clock.now() in reads


def test_snapshot_status_of_uses_the_given_now():
    clock = FakeClock()
    fleet, live = _live_fleet(clock)
    snapshot = fleet.snapshot()

    assert snapshot.status_of(live, clock.now()) == RUNNING
    clock.advance(HOUR)
    assert snapshot.status_of(live, clock.now()) == STUCK


def test_store_upkeep_judges_dead_runs_at_its_now():
    clock = FakeClock()
    fleet, live = _live_fleet(clock)
    upkeep = AppUpkeep(None, APP, clock.monotonic, now=clock.now)
    snapshot = fleet.snapshot()
    assert upkeep._dead(snapshot) == []

    clock.advance(HOUR)

    assert upkeep._dead(snapshot) == [live]


def _list_args():
    return argparse.Namespace(name=APP, sort=None, top=None, last=None, query=None,
                              archived=False, json=False)


def _listed_status(storage, clock):
    console = FakeConsole()
    assert experiment.experiment_list(None, None, storage, _list_args(), console, clock) == 0
    return console.stdout.split()[2]


def _live_store(tmp_path, clock):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    v = seed(storage, APP, verstr(1))
    beat = clock.now().isoformat()
    storage.save_file(APP, v, "run_state.yml",
                      f"state: running\nstarted_at: '{beat}'\nheartbeat: '{beat}'\n"
                      "heartbeat_interval_sec: 10\n")
    return storage


def test_cli_list_derives_status_at_the_io_clock(tmp_path):
    clock = FakeClock(start=LATER)
    storage = _live_store(tmp_path, clock)
    assert _listed_status(storage, clock) == RUNNING

    clock.advance(HOUR)

    assert _listed_status(storage, clock) == STUCK


def _app_status(client):
    body = client.get(f"/api/v1/workspaces/st/apps/{APP}/experiments-status").json()
    return {status for status, n in body["counts"].items() if n}


def test_an_app_given_a_status_clock_derives_at_it(tmp_path):
    clock = FakeClock(start=LATER)
    _live_store(tmp_path, clock)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("st", f"file://{tmp_path / 'store'}")
    io = IO(clock=FakeClock(), env=FakeEnv(), processes=FakeProcesses(), random=FakeRandom(),
            host=FakeHost(), console=FakeConsole())
    deps = real_deps(io, control_plane=None, background_refresh=False, read_only=False,
                     keep_warm=None)
    client = TestClient(build_app(manager, ServerDeps(**{**deps.__dict__,
                                                        "status_clock": clock})))
    assert _app_status(client) == {RUNNING}

    clock.advance(HOUR)

    assert _app_status(client) == {STUCK}
