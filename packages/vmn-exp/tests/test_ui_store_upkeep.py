"""``vmn-exp ui`` keeps a store tidy itself (unless ``--read-only``): after
an index refresh it writes the child markers runs lack and compacts the
metrics of runs whose writer died (failed/stuck), so neither
``backfill-children`` nor ``watch --compact`` has to be run by hand."""
import datetime
import time

import pytest
import yaml

from vmn_exp.core import index as experiment_index
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.writer import create_run
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.store_upkeep import AppUpkeep, StoreUpkeep

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(storage, parent=None, exit_code="none", points=True):
    """A run; *exit_code* None = running, an int = finished, "none" = no state."""
    verstr = create_run(storage, APP, CODE, {"timestamp": _now()}, {}, parent=parent)
    if points:
        w = MetricWriter(storage, APP, verstr, "w")
        for step in range(1, 4):
            w.add("loss", 1.0 / step, step=step)
        w.flush()
    if exit_code != "none":
        state = {"state": "finished" if exit_code is not None else "running", "pid": 1,
                 "host": "h", "started_at": _now(), "heartbeat": _now(),
                 "heartbeat_interval_sec": 30, "exit_code": exit_code}
        storage.save_file(APP, verstr, RUN_STATE_FILE, yaml.dump(state, sort_keys=False))
    return verstr


def _compacted(storage, verstr):
    objects = storage.metric_objects(APP, verstr)
    return bool(objects) and all(is_indexed_file(n) for objs in objects.values()
                                 for n, _ in objs)


def _snap(storage):
    return experiment_index.indexed_snapshot(storage, APP, wait=True)


@pytest.fixture
def storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "root"), area="runs")


def test_writes_the_missing_child_markers(storage):
    outer = _run(storage, points=False)
    kids = [_run(storage, parent=outer, points=False) for _ in range(3)]
    for kid in kids[:2]:
        storage.unmark_child(APP, outer, kid)

    counts = AppUpkeep(storage, APP).run(_snap(storage))

    assert counts["marked"] == 2
    assert storage.list_children(APP, outer) == sorted(kids)


def test_a_parent_is_listed_once_then_new_children_are_marked_directly(storage, monkeypatch):
    outer = _run(storage, points=False)
    _run(storage, parent=outer, points=False)
    upkeep = AppUpkeep(storage, APP)
    upkeep.run(_snap(storage))
    listed = []
    real = storage.list_children
    monkeypatch.setattr(storage, "list_children",
                        lambda app, p: listed.append(p) or real(app, p))
    late = _run(storage, parent=outer, points=False)
    storage.unmark_child(APP, outer, late)

    upkeep.run(_snap(storage))
    upkeep.run(_snap(storage))

    assert listed == []
    assert late in real(APP, outer)


def test_many_new_children_of_a_listed_parent_are_listed_again_not_put(storage, monkeypatch):
    """A cold load shows a parent's children 500 at a time: a page of markers
    is cheaper than a PUT per child that already has one."""
    from vmn_exp.ui import store_upkeep

    monkeypatch.setattr(store_upkeep, "RELIST_OVER", 2)
    outer = _run(storage, points=False)
    _run(storage, parent=outer, points=False)
    upkeep = AppUpkeep(storage, APP)
    upkeep.run(_snap(storage))
    for _ in range(3):
        _run(storage, parent=outer, points=False)  # each writes its own marker
    monkeypatch.setattr(storage, "mark_child", lambda *a: pytest.fail("PUT"))

    assert upkeep.run(_snap(storage))["marked"] == 0


def test_compacts_dead_runs_once_and_leaves_live_ones(storage, monkeypatch):
    failed = _run(storage, exit_code=1)
    live = _run(storage, exit_code=None)
    upkeep = AppUpkeep(storage, APP)

    assert upkeep.run(_snap(storage))["compacted"] == 1
    assert _compacted(storage, failed) and not _compacted(storage, live)

    from vmn_exp.ui import store_upkeep
    monkeypatch.setattr(store_upkeep, "compact_record",
                        lambda *a: pytest.fail("compacted twice"))
    assert upkeep.run(_snap(storage))["compacted"] == 0


def test_a_failing_compaction_is_not_retried_every_pass(storage, monkeypatch):
    from vmn_exp.ui import store_upkeep

    _run(storage, exit_code=1)
    calls = []

    def boom(*a):
        calls.append(a)
        raise OSError("denied")

    monkeypatch.setattr(store_upkeep, "compact_record", boom)
    upkeep = AppUpkeep(storage, APP)
    assert upkeep.run(_snap(storage))["failed"] == 1
    upkeep.run(_snap(storage))
    assert len(calls) == 1


def test_compaction_stops_at_the_pass_budget(storage):
    for _ in range(3):
        _run(storage, exit_code=1)
    ticks = iter([0, 0, 100, 100, 100, 100, 100])
    upkeep = AppUpkeep(storage, APP, clock=lambda: next(ticks))

    assert upkeep.run(_snap(storage), budget_sec=10)["compacted"] == 1
    assert upkeep.run(_snap(storage), budget_sec=1000)["compacted"] == 2


class _Index:
    leading = True


def test_store_upkeep_works_off_the_refresh_thread(storage):
    outer = _run(storage, points=False)
    kid = _run(storage, parent=outer, points=False)
    storage.unmark_child(APP, outer, kid)
    upkeep = StoreUpkeep(interval_sec=0)
    index = _Index()
    try:
        upkeep.note(index, storage, APP)
        upkeep.refreshed(index, _snap(storage))
        assert upkeep.wait_idle(10)
    finally:
        upkeep.stop()
    assert storage.list_children(APP, outer) == [kid]


def test_an_index_this_replica_does_not_lead_is_left_alone(storage):
    outer = _run(storage, points=False)
    kid = _run(storage, parent=outer, points=False)
    storage.unmark_child(APP, outer, kid)
    upkeep = StoreUpkeep(interval_sec=0)
    index = _Index()
    index.leading = False
    try:
        upkeep.note(index, storage, APP)
        upkeep.refreshed(index, _snap(storage))
        assert upkeep.wait_idle(10)
    finally:
        upkeep.stop()
    assert storage.list_children(APP, outer) == []


def test_a_read_only_server_does_no_upkeep(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    assert create_app(manager, read_only=True).state.store_upkeep is None
    assert create_app(manager, background_refresh=True).state.store_upkeep is not None


def test_a_served_store_workspace_gets_its_markers_back(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vmn_exp.storage.open import open_storage
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path / 'store'}"
    store = open_storage(store=uri, area="runs")
    outer = _run(store, points=False)
    kid = _run(store, parent=outer, points=False)
    store.unmark_child(APP, outer, kid)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    app = create_app(manager, background_refresh=True)
    try:
        client = TestClient(app)
        deadline = time.monotonic() + 20
        while store.list_children(APP, outer) != [kid] and time.monotonic() < deadline:
            client.get(f"/api/v1/workspaces/ws/apps/{APP}/experiments?limit=10")
            time.sleep(0.2)
    finally:
        app.state.refresher.stop()
        app.state.store_upkeep.stop()
    assert store.list_children(APP, outer) == [kid]
