"""Plan 25 F1: a warm restart builds its snapshot from the persisted lean
tables. It never selects a record's ``exp_index`` data; a record is decoded
only once a refresh has to refold it."""
import json
import re
import threading

import pytest
from test_index_lean_tables import APP, FINISHED, R, _entry, _run, _seed
from vmn_exp.core import index_lazy, index_store
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage

_RECORD_READ = re.compile(r"\bFROM\s+exp_index\b(?!_)", re.IGNORECASE)
_SNAPSHOT_FIELDS = (
    "rows", "run_states", "edges", "create_notes", "run_state_observed_at",
    "metric_parts", "outputs", "declared_defs", "features", "intents", "hypotheses",
)


class GatedStorage(LocalSnapshotStorage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def list_files(self, app_name, keys=None, identity=False):
        self.gate.wait(30)
        return super().list_files(app_name, keys=keys, identity=identity)


@pytest.fixture
def traced(monkeypatch):
    statements = []
    connect = index_store.connect

    def tracing(path, **kwargs):
        conn = connect(path, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(index_store, "connect", tracing)
    return statements


@pytest.fixture
def decoded(monkeypatch):
    folds = []
    decode = index_lazy.decode_fold

    def counting(key, data):
        folds.append(key)
        return decode(key, data)

    monkeypatch.setattr(index_lazy, "decode_fold", counting)
    return folds


def _persisted(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    _seed(st)
    db = str(tmp_path / "idx.sqlite")
    cold = ExperimentIndex(st, APP, cache_path=db)
    cold.refresh()
    return st, db, cold.snapshot()


def _view(snap):
    return {name: _plain(getattr(snap, name)) for name in _SNAPSHOT_FIELDS}


def _plain(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def test_a_warm_restart_reads_no_record_data(tmp_path, traced, decoded):
    _, db, cold = _persisted(tmp_path)
    traced.clear()
    gated = GatedStorage(str(tmp_path / "repo"), area="runs")
    warm = ExperimentIndex(gated, APP, cache_path=db)
    try:
        snap = warm.snapshot()
        reads = [s for s in traced if _RECORD_READ.search(s)]
        assert reads and all(not re.search(r"\b(data|head)\b", s) for s in reads), reads
        assert decoded == []
        assert _view(snap) == _view(cold)
    finally:
        gated.gate.set()
        warm.wait_revalidated()


def test_a_refresh_decodes_only_the_records_it_refolds(tmp_path, decoded):
    st, db, _ = _persisted(tmp_path)
    _entry(st, R[1], "metrics", 22, values={"loss": 0.35})
    warm = ExperimentIndex(st, APP, cache_path=db)
    warm.snapshot()
    warm.wait_revalidated()
    assert decoded == [R[1]]
    assert warm.snapshot().row(R[1])["metrics"]["loss"] == 0.35


def test_a_record_rewritten_by_another_process_is_read_again(tmp_path):
    st, db, _ = _persisted(tmp_path)
    gated = GatedStorage(str(tmp_path / "repo"), area="runs")
    warm = ExperimentIndex(gated, APP, cache_path=db)
    warm.snapshot()  # rows read; the records' own data not yet

    _run(st, R[4], 60, FINISHED)
    _entry(st, R[3], "metrics", 41, values={"loss": 0.7})
    ExperimentIndex(st, APP, cache_path=db).refresh()  # another process saves R[3]

    gated.gate.set()
    warm.wait_revalidated()
    warm.refresh()
    snap = warm.snapshot()
    assert snap.row(R[3])["metrics"]["loss"] == 0.7
    assert [row["verstr"] for row in snap.rows][-1] == R[4]


def test_a_refresh_that_finds_nothing_changed_reads_no_record(tmp_path, monkeypatch):
    _, db, cold = _persisted(tmp_path)
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    reads = []
    parts = SqliteStore.records_parts

    def counting(self, app_name, seqs):
        reads.extend(seqs)
        return parts(self, app_name, seqs)

    monkeypatch.setattr(SqliteStore, "records_parts", counting)
    warm = ExperimentIndex(st, APP, cache_path=db)
    warm.refresh()
    assert reads == []
    assert _view(warm.snapshot()) == _view(cold)
