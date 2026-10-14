"""The index's helper processes do bulk work cheaply (plan 23 S9).

A cold build's worker processes and the server's I/O helper allocate one
container per value of 100k records: they pause the collector while they do
(see test_gc_pause.py). And the I/O helper hands a restart's persisted
records over undecoded — strings pickle as one copy, while decoded records
cost the helper a pickling and the server an unpickling of ~20M objects.
"""
import gc
import io
import pickle
import sys

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_io_process import _Helper

from vmn_exp.core import index_io_process, index_workers
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"


def _persisted(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    verstr = "0.0.1-dev.abc.r1"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": "t"}, {})
    st.save_file(APP, verstr, "run_state.yml", "state: finished\nexit_code: 0\n")
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()
    return st, db


def _stdio(monkeypatch, request):
    stdin = io.BytesIO(request)
    stdout = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", type("In", (), {"buffer": stdin})())
    monkeypatch.setattr(sys, "stdout", type("Out", (), {"buffer": stdout})())
    return stdout


def test_a_cold_build_worker_loads_with_collection_paused(monkeypatch):
    seen = []
    monkeypatch.setattr(index_workers, "_load_chunk",
                        lambda app, chunk: seen.append(gc.isenabled()) or [])
    _stdio(monkeypatch, pickle.dumps((APP, [])))
    gc.enable()

    index_workers.main()

    assert seen == [False]


def test_the_io_helper_answers_with_collection_paused(tmp_path, monkeypatch):
    st, db = _persisted(tmp_path)
    helper = _Helper(st.io_process_args(), APP, db)
    seen = []
    monkeypatch.setattr(helper.watch, "full_changes",
                        lambda: seen.append(gc.isenabled()) or ({}, set()))
    gc.enable()
    try:
        index_io_process._handle(helper, "full_changes", ())
    finally:
        gc.enable()

    assert seen == [False]


def test_the_io_helper_sends_persisted_records_undecoded(tmp_path):
    st, db = _persisted(tmp_path)
    helper = _Helper(st.io_process_args(), APP, db)

    rows, states = helper.load()

    assert rows and all(isinstance(data, str) for _, data in rows)
    assert states and all(isinstance(data, str) for _, data in states)


def test_the_index_process_decodes_what_the_helper_sent(tmp_path):
    st, db = _persisted(tmp_path)
    index = ExperimentIndex(st, APP, cache_path=db)
    assert index.use_io_process()
    try:
        assert index._load_records() == index._store.load(APP)
    finally:
        index.close()
