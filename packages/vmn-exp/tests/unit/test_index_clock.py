"""The experiment index family runs on the clock it is given (plan 44 G11):
refresh ages, full listings, unreadable retries, freshness, tombstones,
reconnect backoff and similar-search deadlines all move with a FakeClock,
no module clock patched."""
import logging
import sqlite3

import pytest

from fakes.clock import FakeClock
from similar_seed import seed, verstr
from vmn_exp.core import index as index_module
from vmn_exp.core import index_store
from vmn_exp.core.index import RETRY_UNREADABLE_SEC, ExperimentIndex
from vmn_exp.core.index_io_process import _Helper
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.similar_match import SimilarDeadlineExceeded, deadline
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"


@pytest.fixture
def storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _verstrs(snapshot):
    return [row["verstr"] for row in snapshot.rows]


def _rec(v):
    return {"verstr": v, "meta": {"verstr": v}}


def test_refresh_if_stale_uses_the_given_clock(storage):
    clock = FakeClock()
    first = seed(storage, APP, verstr(1))
    index = ExperimentIndex(storage, APP, clock=clock)
    assert _verstrs(index.refresh_if_stale(10)) == [first]
    second = seed(storage, APP, verstr(2))

    clock.advance(9)
    assert _verstrs(index.refresh_if_stale(10)) == [first]

    clock.advance(1)
    assert _verstrs(index.refresh_if_stale(10)) == [first, second]


def test_full_listing_is_due_after_full_sweep_sec(storage):
    clock = FakeClock()
    seed(storage, APP, verstr(1))
    index = ExperimentIndex(storage, APP, full_sweep_sec=300, clock=clock)
    index.refresh()

    clock.advance(299)
    assert not index.full_listing_due()

    clock.advance(1)
    assert index.full_listing_due()


def test_unreadable_record_is_retried_after_the_backoff(storage, monkeypatch):
    clock = FakeClock()
    v = seed(storage, APP, verstr(1))
    broken, real = {v}, index_module.refresh_record

    def refresh_record(key, *args, **kwargs):
        if key in broken:
            raise ValueError("unreadable")
        return real(key, *args, **kwargs)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)
    index = ExperimentIndex(storage, APP, clock=clock).refresh()
    assert index.freshness()["unreadable"]["count"] == 1
    broken.clear()

    clock.advance(RETRY_UNREADABLE_SEC - 1)
    assert index.refresh().freshness()["unreadable"]["count"] == 1

    clock.advance(1)
    assert "unreadable" not in index.refresh().freshness()


def test_tombstones_are_stamped_and_swept_on_the_store_clock(tmp_path):
    clock = FakeClock()
    store = SqliteStore(str(tmp_path / "idx.sqlite"), clock=clock)
    store.save(APP, {"a": _rec("1"), "b": _rec("2")}, set())
    old_gen = store.generation(APP)
    store.save(APP, {}, {"a"})
    assert store.load_since(APP, old_gen)[1] == {"a"}

    clock.advance(index_store.TOMBSTONE_TTL_SEC + 1)
    store.save(APP, {"c": _rec("3")}, set())  # trims the old tombstone

    assert store.load_since(APP, old_gen)[1] is index_store.FULL_LOAD


def test_store_reconnect_waits_out_its_backoff_on_the_given_clock(tmp_path, caplog):
    clock = FakeClock()
    caplog.set_level(logging.WARNING)
    store = SqliteStore(str(tmp_path / "missing-dir" / "idx.sqlite"), clock=clock)
    assert store.save(APP, {"a": _rec("1")}, set()) is False
    (tmp_path / "missing-dir").mkdir()

    assert store.save(APP, {"a": _rec("1")}, set()) is False  # still backing off

    clock.advance(60)
    assert store.save(APP, {"a": _rec("1")}, set()) is True


def test_similar_search_stops_at_its_deadline_on_the_given_clock():
    clock = FakeClock()
    conn = sqlite3.connect(":memory:")
    at = clock.monotonic() + 1

    with deadline(conn, at, clock.monotonic):
        conn.execute("SELECT 1").fetchone()

    clock.advance(1)
    with pytest.raises(SimilarDeadlineExceeded):
        with deadline(conn, at, clock.monotonic):
            conn.execute("SELECT 1").fetchone()


def test_freshness_as_of_follows_the_given_wall_clock(storage):
    clock = FakeClock()
    seed(storage, APP, verstr(1))
    index = ExperimentIndex(storage, APP, clock=clock).refresh()

    assert index.freshness()["as_of"] == clock.now().timestamp()


def test_index_helper_builds_its_index_on_the_given_clock(storage, tmp_path):
    clock = FakeClock()
    seed(storage, APP, verstr(1))
    helper = _Helper((storage.root, storage.area), APP, str(tmp_path / "helper.sqlite"), clock)

    helper.index.refresh()

    assert helper.index.freshness()["as_of"] == clock.now().timestamp()
