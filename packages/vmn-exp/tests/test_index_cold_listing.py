"""A cold journaled remote index serves from its first listed records on.

At 497k runs on S3 the relisting listed every record's files (three LISTs
each) before the first chunk was read, ~75 minutes during which every ui
request waited inside ``snapshot()``. Now names arrive a page at a time,
each page's files are listed and fed to the load queue as they come, and a
request on an index with nothing published yet gets an empty snapshot that
says it is loading."""
import threading
import time

import pytest
from cold_store import APP, ColdStore

from vmn_exp.core import index as index_module
from vmn_exp.core import index_relist
from vmn_exp.core.index import ExperimentIndex

CHUNK = index_module._REMOTE_CHUNK


def _cold(store, tmp_path):
    index = ExperimentIndex(store, APP, cache_path=str(tmp_path / "idx.sqlite"),
                            full_sweep_sec=3600)
    index.journaled = True
    index.reconcile()
    return index


@pytest.fixture
def refreshing():
    """Refresh an index in the background, as the ui's refresher does."""
    stops = []

    def start(index):
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                index.refresh()
                stop.wait(0.01)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        stops.append((stop, thread))
        return index

    yield start
    for stop, thread in stops:
        stop.set()
        thread.join(30)


def _wait(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _rows(index):
    snap = index.published
    return len(snap.rows) if snap is not None else 0


def _loaded(index, n):
    return _wait(lambda: _rows(index) == n and index.freshness()["phase"] == "idle")


def test_the_first_chunk_publishes_after_two_chunks_of_listings_not_all(tmp_path, refreshing):
    store = ColdStore(20_000)
    store.hold_files_after(2 * CHUNK)
    index = refreshing(_cold(store, tmp_path))

    assert _wait(lambda: _rows(index) > 0)
    in_flight = index_relist.LISTING_WORKERS * index_relist.LISTING_CHUNK
    assert store.listed <= 2 * CHUNK + in_flight < 20_000
    store.release.set()
    assert _loaded(index, 20_000)


def test_the_first_publish_follows_the_first_page_of_names(tmp_path, refreshing):
    store = ColdStore(5_000, page=1000)
    store.hold_names_after(1)
    index = refreshing(_cold(store, tmp_path))

    assert _wait(lambda: _rows(index) > 0)
    assert store.name_pages == 1
    store.release.set()
    assert _loaded(index, 5_000)


def test_a_request_never_waits_for_the_first_publish(tmp_path, refreshing):
    store = ColdStore(3_000)
    store.hold_names_after(0)
    index = refreshing(_cold(store, tmp_path))

    started = time.monotonic()
    snap = index.snapshot_now()
    assert time.monotonic() - started < 1.0
    assert snap.rows == () and snap.loading == (0, None)
    assert index.freshness()["phase"] in ("full_listing", "loading_new")
    store.release.set()
    assert _loaded(index, 3_000)
    assert index.snapshot_now().loading is None


def test_the_names_listed_so_far_are_the_total_to_load(tmp_path, refreshing):
    store = ColdStore(3_000)
    store.hold_names_after(1)
    store.hold_files_after(0)
    index = refreshing(_cold(store, tmp_path))

    assert _wait(lambda: index.snapshot_now().loading == (0, 1000))
    store.release.set()
    assert _loaded(index, 3_000)
