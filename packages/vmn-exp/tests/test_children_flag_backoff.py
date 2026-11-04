"""The flag's cheap paths: a cached store whose remote refused one drop does
not retry the remote for every later unmarked child, and the UI's store
upkeep backs off listing an app whose flag attempt was declined."""
import pytest
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.core import index as experiment_index
from vmn_exp.core.writer import create_run
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.store_upkeep import AppUpkeep, UPKEEP_INTERVAL_SEC

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


def _run(storage, parent=None):
    return create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {},
                      parent=parent)


def _broken(*args):
    raise OSError("unreachable")


def _unmarked_run(storage, monkeypatch, parent):
    with monkeypatch.context() as m:
        m.setattr(storage, "mark_child", _broken)
        return _run(storage, parent=parent)


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


@pytest.fixture
def cached(tmp_path, s3):
    return CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "local"), "runs"), s3)


def _count_failing_remote_drops(s3, monkeypatch):
    real, drops = s3.set_children_complete, []

    def failing(app_name, complete, since=None):
        if not complete:
            drops.append(app_name)
            raise OSError("remote unreachable")
        return real(app_name, complete, since=since)

    monkeypatch.setattr(s3, "set_children_complete", failing)
    return drops


def test_a_kept_drop_spares_the_remote_for_later_children(cached, s3, monkeypatch):
    outer = _run(cached)
    cached.set_children_complete(APP, True)
    drops = _count_failing_remote_drops(s3, monkeypatch)
    _unmarked_run(cached, monkeypatch, outer)
    token = cached.children_flag(APP)

    _unmarked_run(cached, monkeypatch, outer)

    assert drops == [APP]
    assert cached.children_flag(APP) != token  # still a new drop, locally
    assert not cached.children_complete(APP)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _declining_upkeep(tmp_path, monkeypatch):
    """An upkeep of an app whose conditional flag set always loses; the
    list of its run listings."""
    local = LocalSnapshotStorage(str(tmp_path / "root"), area="runs")
    outer = _run(local)
    _run(local, parent=outer)
    listings, real = [], local.list_verstrs
    monkeypatch.setattr(local, "list_verstrs", lambda app: listings.append(app) or real(app))
    monkeypatch.setattr(local, "set_children_complete", lambda *a, **kw: False)
    clock = _Clock()
    return local, AppUpkeep(local, APP, clock=clock), clock, listings


def _passes(upkeep, clock, snapshot, count):
    for _ in range(count):
        upkeep.run(snapshot)
        clock.now += UPKEEP_INTERVAL_SEC


def test_a_declined_flag_backs_off_listing_the_app(tmp_path, monkeypatch):
    local, upkeep, clock, listings = _declining_upkeep(tmp_path, monkeypatch)
    snapshot = experiment_index.indexed_snapshot(local, APP, wait=True)
    listings.clear()

    _passes(upkeep, clock, snapshot, 8)

    assert 2 <= len(listings) < 5


def test_a_backed_off_upkeep_flags_once_it_retries(tmp_path, monkeypatch):
    local, upkeep, clock, listings = _declining_upkeep(tmp_path, monkeypatch)
    snapshot = experiment_index.indexed_snapshot(local, APP, wait=True)
    _passes(upkeep, clock, snapshot, 2)
    monkeypatch.undo()

    _passes(upkeep, clock, snapshot, 10)

    assert local.children_complete(APP)
