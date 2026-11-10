"""Plan 34 §4: an index whose I/O helper reads its persisted rows back serves
the newest of them first, as an in-process one does: the helper reads them
(plain parts) while the index process touches no file. And the helper lists
an upgrade's check, a chunk per step."""
import threading

import pytest

from test_fix_index_io_process import FULL_SWEEP_SEC, fs_calls  # noqa: F401  (fixtures)
from test_fix_index_refresh_scale import APP, clock, live_store  # noqa: F401  (fixtures)
from test_index_upgrade_records_19 import _as_records_19
from vmn_exp.core.index import FIRST_ROWS_MAX, ExperimentIndex
from vmn_exp.core.index_io_process import ProcessIO


@pytest.fixture
def held_load(monkeypatch):
    """The helper's read of every persisted row waits for ``.set()``."""
    release, real = threading.Event(), ProcessIO.load
    monkeypatch.setattr(ProcessIO, "load", lambda self: release.wait(20) and real(self))
    yield release
    release.set()


def _restarted(live_store, db):
    first = ExperimentIndex(live_store.st, APP, cache_path=db, full_sweep_sec=FULL_SWEEP_SEC)
    first.refresh()
    total = len(first.snapshot().rows)
    first.close()
    index = ExperimentIndex(live_store.st, APP, cache_path=db, full_sweep_sec=FULL_SWEEP_SEC)
    assert index.use_io_process()
    return index, total


def test_an_offloaded_restart_serves_its_newest_rows_first(
        live_store, clock, tmp_path, held_load, fs_calls):
    index, total = _restarted(live_store, str(tmp_path / "idx.sqlite"))
    refresh = threading.Thread(target=index.refresh, daemon=True)
    try:
        fs_calls["on"] = True
        refresh.start()
        first = index.snapshot_now(wait_sec=10)
        fs_calls["on"] = False
    finally:
        held_load.set()
        refresh.join(20)
        index.close()

    assert 0 < len(first.rows) <= FIRST_ROWS_MAX
    assert first.loading == (len(first.rows), total)
    assert fs_calls["n"] == []


def test_the_helper_lists_an_upgrades_check(live_store, clock, tmp_path):
    db = str(tmp_path / "idx.sqlite")
    index, _ = _restarted(live_store, db)
    index.close()
    _as_records_19(db)
    index = ExperimentIndex(live_store.st, APP, cache_path=db, full_sweep_sec=FULL_SWEEP_SEC)
    assert index.use_io_process()
    try:
        index.refresh()
        assert "checking" not in index.freshness()  # listed: none of its runs compacted
    finally:
        index.close()
