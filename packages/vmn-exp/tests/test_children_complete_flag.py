"""The per-app "every child has its marker" flag: a small object beside the
app's records that no listing takes for a run, written by a complete
backfill and dropped whenever a child's marker fails to be written."""
import pytest
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.cli import backfill_children
from vmn_exp.core.writer import create_run
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


def _run(storage, parent=None):
    return create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {},
                      parent=parent)


@pytest.fixture
def local(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "root"), area="runs")


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


@pytest.fixture(params=["local", "s3"])
def store(request):
    return request.getfixturevalue(request.param)


def test_the_flag_is_off_until_set_and_can_be_dropped(store):
    outer = _run(store)
    assert store.has_child_markers
    assert not store.children_complete(APP)

    store.set_children_complete(APP, True)
    assert store.children_complete(APP)

    store.set_children_complete(APP, False)
    assert not store.children_complete(APP)
    assert store.exists(APP, outer)


def test_the_flag_is_not_a_run(store):
    outer = _run(store)
    _run(store, parent=outer)
    before = (sorted(store.list_verstrs(APP)), sorted(store.list_record_names(APP)),
              sorted(store.list_files(APP)), store.list_apps())

    store.set_children_complete(APP, True)

    after = (sorted(store.list_verstrs(APP)), sorted(store.list_record_names(APP)),
             sorted(store.list_files(APP)), store.list_apps())
    assert after == before
    assert sorted(m["verstr"] for m in store.list_snapshots(APP)) == before[0]


def test_a_failing_marker_drops_the_flag(store, monkeypatch):
    outer = _run(store)
    store.set_children_complete(APP, True)

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "mark_child", broken)
    _run(store, parent=outer)

    assert not store.children_complete(APP)


def test_a_marker_not_written_drops_the_flag(local):
    local.set_children_complete(APP, True)

    _run(local, parent="0.0.1-dev.abc.def.gone")

    assert not local.children_complete(APP)


def test_a_marked_child_keeps_the_flag(store):
    outer = _run(store)
    store.set_children_complete(APP, True)

    _run(store, parent=outer)

    assert store.children_complete(APP)


def test_a_cached_storage_keeps_the_flag_on_its_remote(tmp_path, s3):
    cached = CachedSnapshotStorage(
        LocalSnapshotStorage(str(tmp_path / "local"), "runs"), s3)
    _run(cached)
    assert cached.has_child_markers

    cached.set_children_complete(APP, True)

    assert s3.children_complete(APP)
    assert cached.children_complete(APP)


def _markerless_tree(storage):
    outer = _run(storage)
    kid = _run(storage, parent=outer)
    storage.unmark_child(APP, outer, kid)
    return outer, kid


def test_a_complete_backfill_sets_the_flag(local):
    outer, kid = _markerless_tree(local)

    assert backfill_children.backfill_app(local, APP)["failed"] == 0

    assert local.children_complete(APP)
    assert local.list_children(APP, outer) == [kid]


def test_a_dry_run_backfill_leaves_the_flag_off(local):
    _markerless_tree(local)

    backfill_children.backfill_app(local, APP, dry_run=True)

    assert not local.children_complete(APP)


def test_a_failed_backfill_leaves_the_flag_off(local, monkeypatch):
    _markerless_tree(local)
    monkeypatch.setattr(local, "mark_child", lambda *a: False)

    assert backfill_children.backfill_app(local, APP)["failed"] == 1

    assert not local.children_complete(APP)


def test_a_renamed_pushed_child_marks_its_parent_on_the_remote(tmp_path, s3):
    from push_helpers import APP as PUSH_APP, CODE as PUSH_CODE, X, local_root, \
        make_run, run_meta
    from vmn_exp.core.push_code import CodePusher
    from vmn_exp.core.push_ledger import PushLedger
    from vmn_exp.core.push_rename import push_or_rename
    from vmn_exp.core.push_run import NEW, push_run

    local = local_root(tmp_path)
    outer = make_run(local, tmp_path, verstr=PUSH_CODE + ".outer")
    make_run(local, tmp_path, parent=outer)
    assert push_run(local, s3, PUSH_APP, outer).status == NEW
    s3.save(PUSH_APP, X, run_meta(X, timestamp="2025-05-05T00:00:00Z"), {})

    ledger = PushLedger.for_target(local, PUSH_APP, s3)
    outcome = push_or_rename(local, s3, PUSH_APP, X, ledger,
                             CodePusher(local, s3, PUSH_APP))

    assert outcome.verstr != X
    assert s3.list_children(PUSH_APP, outer) == [outcome.verstr]
    assert local.list_children(PUSH_APP, outer) == [outcome.verstr]
