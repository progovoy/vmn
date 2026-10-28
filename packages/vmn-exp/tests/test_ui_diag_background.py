"""The dump's ``background`` section says what the server's background threads
do: index refreshes, journal ticks, report index refreshes, store upkeep and
board warm-ups, each with its runs, what runs now and how it last failed."""
import threading
import time
import types
import uuid

from vmn_exp.ui import diag, report_index, startup_warmup
from vmn_exp.ui.diag import registry
from vmn_exp.ui.leaderboard_warm import BoardWarmer
from vmn_exp.ui.refresher import Refresher
from vmn_exp.ui.report_index import ReportIndexes
from vmn_exp.ui.store_upkeep import StoreUpkeep


def _unique(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _activity(name, key=None):
    found = [a for a in diag.build_dump()["sections"]["background"]["activities"]
             if a["name"] == name and a["key"] == key]
    return found[0] if found else None


def _wait_for(name, key=None, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _activity(name, key)
        if found and found["runs"]:
            return found
        time.sleep(0.01)
    raise AssertionError(f"{name} {key} never ran")


def setup_module():
    diag.install_default_sections()


def teardown_module():
    registry._SECTIONS.pop("locks", None)
    registry._SECTIONS.pop("background", None)


class _Index:
    def __init__(self, app_name, error=None):
        self.app_name, self._error = app_name, error

    def refresh(self):
        if self._error:
            raise self._error
        return self

    def snapshot(self):
        return types.SimpleNamespace(rows=[], app_name=self.app_name)


def test_an_index_refresh_records_its_failure():
    app = _unique("app")
    refresher = Refresher(interval_sec=0.01)
    try:
        refresher.snapshot(_Index(app, RuntimeError("bucket gone")))
        found = _wait_for("index refresh", app)
    finally:
        refresher.stop()
    assert "bucket gone" in found["last_error"]["error"]


def test_a_journal_tick_is_recorded_per_journal():
    scope = _unique("ws")
    ticked = threading.Event()

    class Journal:
        watched = True

        def __init__(self):
            self.scope = scope

        def watch(self, index):
            pass

        def unwatch(self, index):
            pass

        def tick(self):
            ticked.set()

    journal = Journal()
    refresher = Refresher(interval_sec=0.01)
    try:
        refresher.snapshot(_Index(_unique("app")), journal)
        assert ticked.wait(5)
        found = _wait_for("journal tick", scope)
    finally:
        refresher.stop()
    assert found["last_error"] is None


def test_a_report_index_refresh_is_recorded_per_workspace(monkeypatch):
    ws = types.SimpleNamespace(name=_unique("ws"))
    indexes = ReportIndexes(background=True)
    monkeypatch.setattr(indexes, "_new", lambda ws, storage: _Index("reports"))
    monkeypatch.setattr(report_index, "FOLLOW_INTERVAL_SEC", 0)
    indexes.get(ws, None)
    assert _wait_for("report index refresh", ws.name)["last_ok_ago_sec"] is not None


def test_a_store_upkeep_pass_is_recorded_per_app():
    app = _unique("app")
    index = _Index(app)
    upkeep = StoreUpkeep(interval_sec=0)
    upkeep.note(index, None, app)
    upkeep._apps[index] = types.SimpleNamespace(
        run=lambda snapshot, budget: {"marked": 0, "compacted": 0, "failed": 0})
    try:
        upkeep.refreshed(index, index.snapshot())
        assert upkeep.wait_idle(5)
    finally:
        upkeep.stop()
    assert _wait_for("store upkeep", app)["runs"] == 1


def test_a_board_warm_records_its_failure():
    app = _unique("app")

    class Cache:
        def conf_of(self, snapshot):
            return {}, {}

        def _base(self, snapshot):
            raise ValueError("no base")

    snapshot = types.SimpleNamespace(app_name=app, generation=1, rows=[],
                                     declared_schema=lambda: {})
    snapshot.summarized = lambda schema: snapshot
    BoardWarmer(Cache()).warm(snapshot)
    assert "no base" in _wait_for("board warm", app)["last_error"]["error"]


def test_the_startup_warmup_is_recorded():
    before = (_activity("startup warmup") or {"runs": 0})["runs"]
    app = types.SimpleNamespace(state=types.SimpleNamespace(),
                                router=types.SimpleNamespace(on_startup=[]))
    manager = types.SimpleNamespace(list=lambda: [types.SimpleNamespace(name="ws")])
    startup_warmup.install(app, manager, lambda ws: [], None, None, background=True)
    app.router.on_startup[0]()
    assert app.state.warmed.wait(5)
    assert _wait_for("startup warmup")["runs"] == before + 1
