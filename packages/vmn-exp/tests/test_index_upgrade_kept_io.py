"""An index whose derive runs in the I/O helper serves the rows an in-place
upgrade kept, ``loading``, while the helper re-derives them (plan 33 §2.3),
as an in-process index does: the helper reads them, once, and the index
process still touches no file."""
import threading
import time

import pytest

from test_fix_index_io_process import FULL_SWEEP_SEC, fs_calls  # noqa: F401  (fixtures)
from test_fix_index_refresh_scale import APP, clock, live_store  # noqa: F401  (fixtures)
from test_index_upgrade_in_place import _as_records_18
from vmn_exp.core import index_store_reads
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_io_process import ProcessIO


@pytest.fixture
def held(monkeypatch):
    """``(hold, release)``: *hold(owner, name)* makes that call wait for
    ``release.set()``."""
    release = threading.Event()

    def hold(owner, name):
        real = getattr(owner, name)

        def waits(*args, **kwargs):
            release.wait(20)
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, waits)

    yield hold, release
    release.set()


def verstrs(snap):
    return {row["verstr"] for row in snap.rows}


def upgraded(live_store, db, io, outdate):
    """``(index, its verstrs)``: an index over *db* once loaded, then
    *outdate(db)*; its I/O helper used when *io*."""
    first = ExperimentIndex(live_store.st, APP, cache_path=db, full_sweep_sec=FULL_SWEEP_SEC)
    first.refresh()
    want = verstrs(first.snapshot())
    first.close()
    outdate(db)
    index = ExperimentIndex(live_store.st, APP, cache_path=db, full_sweep_sec=FULL_SWEEP_SEC)
    assert index.use_io_process() is io
    return index, want


def _mid_derive_snapshot(index):
    deadline, snap = time.monotonic() + 10, None
    while time.monotonic() < deadline:
        snap = index.snapshot_now(wait_sec=0.1)
        if snap is not None and snap.loading is not None and snap.rows:
            break
        time.sleep(0.05)
    return snap


def serves_kept_rows_mid_derive(index, want, release):
    """Mid-derive *index* serves *want*'s rows ``loading``; once released,
    the same rows, loaded."""
    refresh = threading.Thread(target=index.refresh)
    refresh.start()
    try:
        snap = _mid_derive_snapshot(index)
        assert snap is not None and snap.loading is not None
        assert snap.loading[1] == len(want)
        assert verstrs(snap) == want
    finally:
        release.set()
        refresh.join(20)
    final = index.snapshot()
    assert final.loading is None and verstrs(final) == want


def test_an_offloaded_derive_serves_the_kept_rows_loading_from_the_helper(
        live_store, clock, tmp_path, held, fs_calls):
    hold, release = held
    hold(ProcessIO, "derive")
    index, want = upgraded(live_store, str(tmp_path / "idx.sqlite"), True,
                           lambda db: _as_records_18(db, ()))
    try:
        fs_calls["on"] = True
        serves_kept_rows_mid_derive(index, want, release)
        fs_calls["on"] = False
    finally:
        index.close()
    assert fs_calls["n"] == []


def test_the_helper_reads_the_kept_rows_once(live_store, clock, tmp_path, monkeypatch):
    from vmn_exp.core.index_io_process import _Helper

    reads = []
    real = index_store_reads.LeanReads.load_kept
    monkeypatch.setattr(index_store_reads.LeanReads, "load_kept",
                        lambda store, app: reads.append(app) or real(store, app))
    db = str(tmp_path / "idx.sqlite")
    index, want = upgraded(live_store, db, True, lambda db: _as_records_18(db, ()))
    index.close()
    helper = _Helper(live_store.st.io_process_args(), APP, db)

    kept = helper.kept()
    helper.derive()

    order, lean, _ = kept
    assert {lean[key][0]["verstr"] for key in order} == want
    assert reads == [APP]
