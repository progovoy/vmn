"""A cold journaled load publishes every run's row before reading the rest of
any run's log and metric segments: its listing hands the records over a
batch at a time, and reading each batch's stuck runs' hundreds of segments
before the next batch's rows held the board back (at 100k S3 runs half of
the load's GETs were such segments)."""
import threading

from vmn_exp.core import index as index_module
from vmn_exp.core import index_sweep_behind
from vmn_exp.core.index import ExperimentIndex

from test_fix_index_s3_rows_first import (  # noqa: F401  (the s3 fixture)
    APP,
    N,
    SEGMENTS,
    _hold_segment_reads,
    _rows_once,
    _seed,
    _storage,
    s3,
)


def test_every_row_publishes_before_any_rest_is_read(s3, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", 1)
    monkeypatch.setattr(index_sweep_behind, "RELIST_PER_REFRESH", 2)
    _seed(_storage())
    storage, release = _storage(), threading.Event()
    gave_up = _hold_segment_reads(storage, release)
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"), full_sweep_sec=3600)
    index.journaled = True
    index.reconcile()
    stop = threading.Event()

    def refreshing():
        while not stop.is_set():
            index.refresh()
            stop.wait(0.01)

    thread = threading.Thread(target=refreshing, daemon=True)
    thread.start()
    try:
        assert len(_rows_once(index, N)) == N
        assert not gave_up.is_set()
    finally:
        release.set()
    try:
        rows = _rows_once(index, N)
        for _ in range(500):
            rows = index.snapshot().rows
            if all(r["metrics"].get("loss") == float(SEGMENTS) for r in rows):
                break
            stop.wait(0.02)
        assert all(r["metrics"]["loss"] == float(SEGMENTS) for r in rows)
    finally:
        stop.set()
        thread.join(30)
