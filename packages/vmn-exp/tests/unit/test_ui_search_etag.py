"""The ⌘K search route's ETag (plan 23 S8) moves exactly when its answer
does: a time bucket passing or an index refresh that leaves the matched runs
as they were still answers ``304``; a run joining the matches, or a matched
running run going stuck, answers ``200``. The clock is a fake one and the
index refreshes inline, so the race of a refresh or a bucket boundary
between two requests is put in by hand."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from similar_seed import seed, verstr
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.core.ports import IO
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.app_deps import ServerDeps, real_deps
from vmn_exp.ui.leaderboard_cache import BUCKET_SEC
from vmn_exp.ui.server import build_app
from vmn_exp.ui.workspaces import WorkspaceManager

APP = "app"
URL = f"/api/v1/workspaces/st/apps/{APP}/search"
# Later than any store write time a test leaves, so the heartbeat decides.
LATER = datetime(2099, 1, 1, tzinfo=timezone.utc)
HOUR = 3600


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


class Server:
    def __init__(self, tmp_path):
        self.clock = FakeClock(start=LATER)
        self.storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
        self.runs = 0
        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_store("st", f"file://{tmp_path / 'store'}")
        io = IO(clock=self.clock, env=FakeEnv(), processes=FakeProcesses(),
                random=FakeRandom(), host=FakeHost(), console=FakeConsole())
        deps = real_deps(io, control_plane=None, background_refresh=False, read_only=False,
                         keep_warm=None)
        self.client = TestClient(build_app(manager, ServerDeps(**deps.__dict__)))

    def add(self, name, running=False):
        self.runs += 1
        v = seed(self.storage, APP, verstr(self.runs), name=name,
                 exit_code=None if running else 0)
        if running:
            beat = self.clock.now().isoformat()
            self.storage.save_file(APP, v, "run_state.yml",
                                   f"state: running\nstarted_at: '{beat}'\nheartbeat: '{beat}'\n"
                                   "heartbeat_interval_sec: 10\n")
        return v

    def search(self, text, etag=None):
        headers = {"If-None-Match": etag} if etag else {}
        return self.client.get(URL, params={"text": text}, headers=headers)


@pytest.fixture
def server(tmp_path):
    server = Server(tmp_path)
    server.add("lr_grid")
    server.add("lr_grid-t1")
    server.add("other")
    return server


def test_a_repeat_after_a_time_bucket_passes_is_a_304(server):
    first = server.search("grid")
    server.clock.advance(BUCKET_SEC * 3)
    assert server.search("grid", first.headers["etag"]).status_code == 304


def test_a_refresh_that_leaves_the_matches_alone_keeps_the_etag(server):
    first = server.search("grid")
    server.add("unrelated")
    again = server.search("grid", first.headers["etag"])
    assert again.status_code == 304
    assert server.search("unrelated").json()["results"]  # the refresh did happen


def test_a_refresh_adding_a_matching_run_changes_the_etag(server):
    first = server.search("grid")
    server.add("lr_grid-t2")
    again = server.search("grid", first.headers["etag"])
    assert again.status_code == 200
    assert len(again.json()["results"]) == 3


def test_a_matched_running_run_going_stuck_changes_the_etag(server):
    server.add("grid_live", running=True)
    first = server.search("grid")
    assert {r["status"] for r in first.json()["results"]} == {"succeeded", "running"}
    server.clock.advance(HOUR)
    again = server.search("grid", first.headers["etag"])
    assert again.status_code == 200
    assert "stuck" in {r["status"] for r in again.json()["results"]}


def test_other_text_is_a_200(server):
    first = server.search("grid")
    assert server.search("other", first.headers["etag"]).status_code == 200
