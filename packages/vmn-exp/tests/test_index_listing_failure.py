"""A refresh that fails after its listing took changes (an S3 LIST answering
``SlowDown`` past botocore's retries, a save the index store refuses) lists
again what it took — the hints, the records it listed — and nothing more. It
used to forget every baseline, so the next refresh re-listed the whole store:
more of the requests the store was refusing (at ~490k S3 records, hours of
LISTs behind serving)."""
import os

import pytest
from botocore.exceptions import ClientError
from s3_helpers import meta, s3_storage
from test_fix_index_io_process import offloaded  # noqa: F401  (fixture)
from test_fix_index_refresh_scale import clock, live_store  # noqa: F401  (fixtures)
from test_index_metric_reads_s3 import APP, V, s3  # noqa: F401  (fixture)
from vmn_exp.core import index as experiment_index
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_io_process import IOProcessError
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage

W = "1.0.0-dev.w"
DONE = "state: succeeded\nexit_code: 0\n"
FAILED = "state: failed\nexit_code: 1\n"


def _slow_down():
    return ClientError({"Error": {"Code": "SlowDown", "Message": "Please reduce your request rate."}},
                       "ListObjectsV2")


class Listings:
    """Every ``list_files`` *storage* answers (None: a full listing); the
    next ``fail`` keyed ones raise ``SlowDown``."""

    def __init__(self, storage, monkeypatch):
        self.calls, self.fail = [], 0
        self._real = storage.list_files
        monkeypatch.setattr(storage, "list_files", self)

    def __call__(self, app_name, keys=None, **kw):
        self.calls.append(None if keys is None else set(keys))
        if keys is not None and self.fail:
            self.fail -= 1
            raise _slow_down()
        return self._real(app_name, keys=keys, **kw)


def _statuses(index):
    snapshot = index.refresh().snapshot()
    return {r["verstr"]: snapshot.status_of(r["verstr"]) for r in snapshot.rows}


def test_a_throttled_listing_is_followed_by_no_full_listing(s3, tmp_path, monkeypatch):
    s3.save(APP, W, meta(W), {})
    s3.save_file(APP, W, "run_state.yml", DONE)
    index = ExperimentIndex(s3_storage(), APP, os.path.join(tmp_path, "i.sqlite"),
                            full_sweep_sec=3600)
    assert _statuses(index) == {V: "running", W: "succeeded"}
    s3.save_file(APP, V, "run_state.yml", DONE)
    s3.save_file(APP, W, "run_state.yml", FAILED)  # settled: listed only when hinted
    index.hint(W)
    listings = Listings(index._storage, monkeypatch)
    listings.fail = 1

    with pytest.raises(ClientError):
        index.refresh()

    assert _statuses(index) == {V: "succeeded", W: "failed"}
    assert None not in listings.calls


# -- a journaled local index ------------------------------------------------------

RECONCILE_SEC = 10
FINISHED = "state: finished\nexit_code: 0\n"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _make(st, i):
    verstr = f"0.0.1-dev.abc.r{i}"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
    st.save_file(APP, verstr, "run_state.yml", FINISHED)
    return verstr


def _metric(st, verstr, value):
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "metrics",
                                            "values": {"acc": value}})


def _acc(index, verstr):
    return {r["verstr"]: r for r in index.rows()}[verstr]["metrics"].get("acc")


class _SaveFailsOnce:
    def __init__(self, store, monkeypatch):
        self.armed, self._real = False, store.save
        monkeypatch.setattr(store, "save", self)

    def __call__(self, *args, **kwargs):
        if self.armed:
            self.armed = False
            raise OSError("disk I/O error")
        return self._real(*args, **kwargs)


def test_a_failed_save_after_the_check_relists_and_persists_what_it_found(
    tmp_path, monkeypatch
):
    clock = Clock()
    monkeypatch.setattr(experiment_index, "_monotonic", clock)
    st = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    runs = [_make(st, i) for i in range(10)]
    cache = str(tmp_path / "i.sqlite")
    index = ExperimentIndex(st, APP, cache, full_sweep_sec=RECONCILE_SEC)
    index.journaled = True
    index.refresh()
    _metric(st, runs[0], 0.75)  # unannounced: the next check's slice finds it
    listings = Listings(st, monkeypatch)
    save = _SaveFailsOnce(index._store, monkeypatch)
    save.armed = True

    clock.now += 1
    with pytest.raises(OSError):
        index.refresh()
    assert any(runs[0] in (keys or ()) for keys in listings.calls)  # the check took it
    listings.calls.clear()
    clock.now += 1
    index.refresh()

    assert any(runs[0] in (keys or ()) for keys in listings.calls)
    assert None not in listings.calls
    assert _acc(index, runs[0]) == 0.75
    persisted = SqliteStore(cache).load(APP)[runs[0]]
    assert persisted["fold"]["metrics"]["acc"][0] == 0.75


# -- the I/O helper process -------------------------------------------------------


def test_a_helper_listing_that_fails_is_followed_by_no_full_listing(
    offloaded, live_store, clock, monkeypatch  # noqa: F811
):
    offloaded.refresh()
    watch = offloaded._io.watch
    quiet = next(r["verstr"] for r in offloaded.snapshot().rows if r["verstr"] not in live_store.live)
    live_store.log(quiet, 7)  # no sig shows it: only its hint does
    offloaded.hint(quiet)
    fulls, real_files = [], watch.files
    failing = [True]

    def files(keys):
        if failing and failing.pop():
            raise IOProcessError("index I/O helper failed files")
        return real_files(keys)

    monkeypatch.setattr(watch, "files", files)
    real_full = watch.full_changes
    monkeypatch.setattr(watch, "full_changes", lambda: fulls.append(1) or real_full())
    clock.now += 1
    with pytest.raises(IOProcessError):
        offloaded.refresh()

    clock.now += 1
    offloaded.refresh()

    assert fulls == []
    assert offloaded.snapshot().row(quiet)["metrics"]["loss"] == 7


def test_a_full_listing_whose_save_fails_is_listed_fully_again(tmp_path, monkeypatch):
    """Not record by record: on S3 that is three LISTs a record, where a full
    listing is one per 1000 objects."""
    st = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    runs = {_make(st, i) for i in range(10)}
    cache = str(tmp_path / "i.sqlite")
    index = ExperimentIndex(st, APP, cache, full_sweep_sec=3600)
    _SaveFailsOnce(index._store, monkeypatch).armed = True
    with pytest.raises(OSError):
        index.refresh()
    listings = Listings(st, monkeypatch)

    index.refresh()

    assert listings.calls == [None]
    assert {r["verstr"] for r in index.rows()} == runs
    assert set(SqliteStore(cache).load(APP)) == runs
