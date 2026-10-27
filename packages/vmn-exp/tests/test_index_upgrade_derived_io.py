"""An index whose filesystem work runs in the I/O helper re-derives an upgraded
file's rows in the helper too: the index process touches neither the files
nor SQLite, and serves the re-derived rows, not the stale ones."""
from test_fix_index_io_process import FULL_SWEEP_SEC, fs_calls  # noqa: F401  (fixtures)
from test_fix_index_refresh_scale import APP, clock, live_store  # noqa: F401  (fixtures)
from test_index_upgrade_derived import _as_older_derived
from vmn_exp.core.index import ExperimentIndex


def _offloaded(live_store, db):
    index = ExperimentIndex(live_store.st, APP, cache_path=db, full_sweep_sec=FULL_SWEEP_SEC)
    assert index.use_io_process()
    return index


def test_an_offloaded_index_re_derives_in_the_helper(live_store, clock, fs_calls, tmp_path):
    db = str(tmp_path / "idx.sqlite")
    first = _offloaded(live_store, db)
    first.refresh()
    want = {row["verstr"]: dict(row) for row in first.snapshot().rows}
    first.close()
    _as_older_derived(db)

    index = _offloaded(live_store, db)
    try:
        fs_calls["on"] = True
        index.refresh()
        fs_calls["on"] = False
        got = {row["verstr"]: dict(row) for row in index.snapshot().rows}
    finally:
        index.close()

    assert fs_calls["n"] == []
    assert got == want
