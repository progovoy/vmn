"""The dump's ``locks`` section names the server's locks a stuck request can
queue behind: a report index catching up a journal for minutes, an
experiment index refresh, the refresher, the store upkeep, a board base."""
import threading
import time
import types
import uuid

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui import diag
from vmn_exp.ui.diag import registry
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.refresher import Refresher
from vmn_exp.ui.report_index import ReportIndexes
from vmn_exp.ui.store_upkeep import StoreUpkeep


def _unique(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _held(name):
    sections = diag.build_dump()["sections"]
    return [h for h in sections["locks"]["held"] if h["name"] == name]


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _hold(lock, thread_name):
    acquired, release = threading.Event(), threading.Event()

    def hold():
        with lock:
            acquired.set()
            release.wait(10)

    thread = threading.Thread(target=hold, name=thread_name, daemon=True)
    thread.start()
    assert acquired.wait(5)
    return release, thread


def _assert_named_holder(lock, name):
    thread_name = _unique("holder")
    release, thread = _hold(lock, thread_name)
    try:
        assert [h["holder"] for h in _held(name)] == [thread_name]
    finally:
        release.set()
        thread.join(5)


def setup_module():
    diag.install_default_sections()


def teardown_module():
    registry._SECTIONS.pop("locks", None)
    registry._SECTIONS.pop("background", None)


def test_a_report_index_held_by_a_journal_catch_up_names_its_waiters(tmp_path):
    ws = types.SimpleNamespace(name=_unique("ws"), store=None, path=str(tmp_path))
    index = ReportIndexes(background=False)._new(ws, LocalSnapshotStorage(str(tmp_path)))
    release, holder = _hold(index._lock, "vmn-ui-reports")
    request = threading.Thread(target=index.refresh, name="request-1", daemon=True)
    request.start()
    name = f"report index:{ws.name}"
    try:
        assert _wait_until(lambda: _held(name) and _held(name)[0]["waiters"])
        entry = _held(name)[0]
        assert entry["holder"] == "vmn-ui-reports"
        assert [w["thread"] for w in entry["waiters"]] == ["request-1"]
    finally:
        release.set()
        holder.join(5)
        request.join(5)
    stats = {s["name"]: s for s in diag.build_dump()["sections"]["locks"]["stats"]}
    assert stats[name]["contended"] == 1


def test_an_experiment_index_lock_is_named_with_its_app(tmp_path):
    app = _unique("app")
    index = ExperimentIndex(LocalSnapshotStorage(str(tmp_path)), app)
    _assert_named_holder(index._lock, f"index refresh:{app}")
    assert index.refreshing is False


def test_the_refresher_lock_is_traced():
    refresher = Refresher()
    _assert_named_holder(refresher._lock, "refresher")
    assert refresher.watched() == []


def test_the_store_upkeep_lock_is_traced():
    upkeep = StoreUpkeep()
    _assert_named_holder(upkeep._lock, "store upkeep")
    assert upkeep.wait_idle(1)


def test_a_board_base_lock_is_named_with_its_app():
    app = _unique("app")
    meta = {"verstr": "1.0.0-dev.r0001", "timestamp": "2026-01-01T00:00:00Z"}
    row = experiment_row(1, meta, [{"timestamp": "t", "type": "create", "params": {}}])
    snapshot = IndexSnapshot.build(app, 1, [row], {})
    LeaderboardCache().page(snapshot, {}, limit=5)
    stats = diag.build_dump()["sections"]["locks"]["stats"]
    assert f"leaderboard base:{app}" in {s["name"] for s in stats}
