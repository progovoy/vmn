"""The "every child has its marker" flag never lies: a scan cannot set it
over a drop that landed while it listed, a cached store whose remote drop
failed keeps the drop locally (and replays it), and the UI's store upkeep
sets it after a clean pass through the same conditional write."""
from types import SimpleNamespace

import pytest
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.cli import backfill_children
from vmn_exp.cli import prune as prune_mod
from vmn_exp.core import index as experiment_index
from vmn_exp.core.writer import create_run
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.store_upkeep import AppUpkeep

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


def _run(storage, parent=None):
    return create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {},
                      parent=parent)


def _broken(*args):
    raise OSError("unreachable")


def _unmarked_run(storage, monkeypatch, parent):
    """A child whose marker fails to write (so its creation drops the flag)."""
    with monkeypatch.context() as m:
        m.setattr(storage, "mark_child", _broken)
        return _run(storage, parent=parent)


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


@pytest.fixture
def cached(tmp_path, s3):
    return CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "local"), "runs"), s3)


def _race_the_listing(storage, monkeypatch, outer):
    """While the scan lists the app, another writer creates a child whose
    marker fails — after the listing has been taken."""
    real = storage.list_verstrs
    late = []

    def listing(app_name):
        names = list(real(app_name))
        if not late:
            late.append(_unmarked_run(storage, monkeypatch, outer))
        return names

    monkeypatch.setattr(storage, "list_verstrs", listing)
    return late


# -- 1. scan vs. drop ---------------------------------------------------------


def test_a_drop_during_the_scan_keeps_the_flag_unset(store, monkeypatch):
    outer = _run(store)
    late = _race_the_listing(store, monkeypatch, outer)

    counts = backfill_children.backfill_app(store, APP)

    assert late and counts["failed"] == 0
    assert not store.children_complete(APP)


def test_a_drop_before_the_scan_does_not_stop_the_scan_flagging(store, monkeypatch):
    outer = _run(store)
    _unmarked_run(store, monkeypatch, outer)
    assert not store.children_complete(APP)

    backfill_children.backfill_app(store, APP)

    assert store.children_complete(APP)


def test_the_scan_after_a_raced_one_flags_the_app(store, monkeypatch):
    outer = _run(store)
    late = _race_the_listing(store, monkeypatch, outer)
    backfill_children.backfill_app(store, APP)
    monkeypatch.undo()

    backfill_children.backfill_app(store, APP)

    assert store.children_complete(APP)
    assert store.list_children(APP, outer) == late


def test_a_conditional_set_fails_once_the_flag_changed(store):
    _run(store)
    token = store.children_flag(APP)
    store.set_children_complete(APP, False)

    assert store.set_children_complete(APP, True, since=token) is False
    assert not store.children_complete(APP)
    assert store.set_children_complete(APP, True, since=store.children_flag(APP)) is True
    assert store.children_complete(APP)


def test_every_drop_is_a_new_token(store):
    _run(store)
    store.set_children_complete(APP, False)
    token = store.children_flag(APP)

    store.set_children_complete(APP, False)

    assert store.children_flag(APP) != token


# -- 2. cached storage whose remote drop fails --------------------------------


def _flag_on_remote(cached, s3):
    outer = _run(cached)
    cached.set_children_complete(APP, True)
    assert s3.children_complete(APP)
    return outer


def _remote_drop_fails(s3, monkeypatch):
    real = s3.set_children_complete

    def failing(app_name, complete, since=None):
        if not complete:
            raise OSError("remote unreachable")
        return real(app_name, complete, since=since)

    monkeypatch.setattr(s3, "set_children_complete", failing)


def test_a_failed_remote_drop_is_kept_locally(cached, s3, monkeypatch):
    outer = _flag_on_remote(cached, s3)
    _remote_drop_fails(s3, monkeypatch)

    _unmarked_run(cached, monkeypatch, outer)

    assert s3.children_complete(APP)  # the remote still says so…
    assert not cached.children_complete(APP)  # …but this host does not trust it


def test_the_kept_drop_is_replayed_on_the_remote(cached, s3, monkeypatch):
    outer = _flag_on_remote(cached, s3)
    with monkeypatch.context() as m:
        _remote_drop_fails(s3, m)
        _unmarked_run(cached, m, outer)

    assert not cached.children_complete(APP)

    assert not s3.children_complete(APP)
    assert not cached.children_complete(APP)


def test_a_failed_remote_drop_still_protects_the_parent(cached, s3, monkeypatch):
    outer = _flag_on_remote(cached, s3)
    _remote_drop_fails(s3, monkeypatch)
    kid = _unmarked_run(cached, monkeypatch, outer)

    args = SimpleNamespace(version=[outer], keep=None, older_than=None, force=False,
                           dry_run=False, query=None, protect_tag=None)
    assert prune_mod.experiment_prune(None, {}, cached, args, APP) == 0

    assert cached.exists(APP, outer) and cached.exists(APP, kid)


def test_a_scan_through_the_cache_clears_the_kept_drop(cached, s3, monkeypatch):
    outer = _flag_on_remote(cached, s3)
    with monkeypatch.context() as m:
        _remote_drop_fails(s3, m)
        kid = _unmarked_run(cached, m, outer)

    backfill_children.backfill_app(cached, APP)

    assert cached.children_complete(APP)
    assert s3.children_complete(APP)
    assert kid in cached.list_children(APP, outer)


# -- 3. the UI's store upkeep --------------------------------------------------


def _snap(storage):
    return experiment_index.indexed_snapshot(storage, APP, wait=True)


def _markerless_tree(storage):
    outer = _run(storage)
    kid = _run(storage, parent=outer)
    storage.unmark_child(APP, outer, kid)
    return outer, kid


def test_upkeep_flags_the_app_after_a_clean_pass(local):
    _markerless_tree(local)

    AppUpkeep(local, APP).run(_snap(local))

    assert local.children_complete(APP)


def test_upkeep_does_not_flag_after_a_failed_mark(local, monkeypatch):
    _markerless_tree(local)
    monkeypatch.setattr(local, "mark_child", _broken)

    assert AppUpkeep(local, APP).run(_snap(local))["failed"] == 1

    assert not local.children_complete(APP)


def test_upkeep_does_not_flag_over_a_drop_during_its_check(local, monkeypatch):
    outer, _ = _markerless_tree(local)
    snapshot = _snap(local)
    _race_the_listing(local, monkeypatch, outer)

    AppUpkeep(local, APP).run(snapshot)

    assert not local.children_complete(APP)


def test_upkeep_marks_a_run_its_snapshot_lacks_before_flagging(local):
    outer = _run(local)
    snapshot = _snap(local)
    late = _run(local, parent=outer)
    local.unmark_child(APP, outer, late)

    AppUpkeep(local, APP).run(snapshot)

    assert local.list_children(APP, outer) == [late]
    assert local.children_complete(APP)


def test_upkeep_leaves_a_flagged_app_alone(local, monkeypatch):
    _run(local)
    local.set_children_complete(APP, True)
    snapshot = _snap(local)
    monkeypatch.setattr(local, "list_verstrs", lambda app: pytest.fail("listed"))

    AppUpkeep(local, APP).run(snapshot)

    assert local.children_complete(APP)
