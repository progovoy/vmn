"""Plan 34 §4: after an in-place upgrade a restarted index publishes before
it reads the kept rows back (O(runs): minutes at ~734k runs on S3, an empty
board saying ``loading 0, total null`` meanwhile). It says the total at once,
then serves the newest kept rows, and reads the rest with collection paused,
building no lazy record it would discard."""
import gc
import threading

import pytest

import vmn_exp.core.index as index_module
from journal_index_helpers import APP, make, storage
from test_index_upgrade_records_19 import _as_records_19
from vmn_exp.core import index_store_reads
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_first_rows import kept_parts
from vmn_exp.core.index_snapshot import RowCache
from vmn_exp.core.index_store import SqliteStore

N, FIRST = 30, 10


@pytest.fixture
def outdated(tmp_path, monkeypatch):
    """``(storage, index file)``: N runs a previous life indexed, its
    records since marked version 19; a store that says it is remote."""
    st = storage(tmp_path)
    for i in range(N):
        make(st, i)
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh().close()
    _as_records_19(db)
    monkeypatch.setattr(st, "is_remote", lambda: True, raising=False)
    monkeypatch.setattr(index_module, "FIRST_ROWS", FIRST)
    return st, db


@pytest.fixture
def held_kept(monkeypatch):
    """``(entered, release)``: the kept rows' read waits for *release*."""
    entered, release, real = threading.Event(), threading.Event(), index_module.kept_parts

    def held(*args):
        entered.set()
        release.wait(10)
        return real(*args)

    monkeypatch.setattr(index_module, "kept_parts", held)
    yield entered, release
    release.set()


def _while_kept_is_read(index, entered):
    refresh = threading.Thread(target=index.refresh, daemon=True)
    refresh.start()
    assert entered.wait(10)
    return refresh


def test_the_total_is_known_before_the_kept_rows_are_read(outdated, held_kept, monkeypatch):
    st, db = outdated
    entered, release = held_kept
    monkeypatch.setattr(index_module, "first_rows", lambda *a, **k: None)
    index = ExperimentIndex(st, APP, cache_path=db)

    refresh = _while_kept_is_read(index, entered)
    snap = index.snapshot_now(0)
    release.set()
    refresh.join(10)

    assert snap.loading == (0, N)
    assert not snap.rows


def test_the_newest_kept_rows_serve_before_the_rest_are_read(outdated, held_kept):
    st, db = outdated
    entered, release = held_kept
    index = ExperimentIndex(st, APP, cache_path=db)

    refresh = _while_kept_is_read(index, entered)
    first = index.snapshot_now(0)
    release.set()
    refresh.join(10)
    full = index.snapshot()

    newest = [r["verstr"] for r in full.rows[-FIRST:]]
    assert [r["verstr"] for r in first.rows] == newest
    assert first.loading == (FIRST, N)


def test_the_kept_read_and_its_rows_run_with_collection_paused(outdated, monkeypatch):
    st, db = outdated
    seen = []
    real_kept, real_seed = SqliteStore.load_kept, RowCache.seed
    monkeypatch.setattr(SqliteStore, "load_kept",
                        lambda self, app: seen.append(gc.isenabled()) or real_kept(self, app))
    monkeypatch.setattr(RowCache, "seed",
                        lambda self, lean: seen.append(gc.isenabled()) or real_seed(self, lean))
    assert gc.isenabled()
    index = ExperimentIndex(st, APP, cache_path=db)

    index.refresh()

    assert len(seen) >= 2 and not any(seen)


def test_the_kept_read_builds_no_lazy_record(outdated, monkeypatch):
    st, db = outdated
    store = SqliteStore(db)
    built = []
    monkeypatch.setattr(index_store_reads, "LazyRecord", lambda *a: built.append(a))
    monkeypatch.setattr(index_store_reads, "_Prefetch", lambda *a, **k: built.append(a))

    order, lean, states = kept_parts(store, APP)

    assert len(order) == N and set(lean) == set(order) == set(states)
    assert built == []
