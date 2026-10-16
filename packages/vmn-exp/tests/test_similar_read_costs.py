"""What a similar-runs answer reads besides its FTS match: the shown runs'
facts and run states in one query each from the persisted index, and a
snapshot sync skips the runs whose row and command did not move."""
import pytest
from similar_seed import features, finished, seed, verstr
from vmn_exp.core import similar_filing, similar_fts
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.similar_corpus import file_scope, memory_conn
from vmn_exp.core.similar_filing import SnapshotFiler
from vmn_exp.core.similar_search import search, snapshot_scope, text_target
from vmn_exp.snapshot import open_storage

APP = "trainer"
RUNS = 8

pytestmark = pytest.mark.skipif(not similar_fts.fts5_available(),
                                reason="no SQLite FTS5 here")


@pytest.fixture
def indexed(tmp_path):
    storage = open_storage(root=str(tmp_path / "store"), area="runs")
    for n in range(RUNS):
        seed(storage, APP, verstr(n), intent={"text": f"focal loss try {n}"},
             changes=features([f"f{n}.py"]), goal=("loss", "min"), metrics={"loss": n})
        finished(storage, APP, verstr(n))
    path = str(tmp_path / "index.sqlite")
    index = ExperimentIndex(storage, APP, path, full_sweep_sec=0)
    yield storage, index, path
    index.close()


def test_the_shown_runs_facts_are_read_in_one_query_each(indexed):
    storage, index, path = indexed
    snapshot = index.refresh().snapshot()
    expected = search(storage, APP, snapshot_scope(APP, snapshot), text_target("focal"),
                      top=RUNS)
    scope = file_scope(APP, path)
    statements = []
    scope.conn.set_trace_callback(statements.append)
    try:
        got = search(storage, APP, scope, text_target("focal"), top=RUNS)
    finally:
        scope.conn.set_trace_callback(None)
    assert len(got) == RUNS and got == expected
    sides = [s for s in statements if "FROM exp_sides" in s and "declared_defs" not in s]
    states = [s for s in statements if "FROM exp_index_state" in s]
    assert len(sides) == 1 and "outputs" not in sides[0]
    assert len(states) == 1


def test_a_heartbeat_only_sync_derives_no_facts(indexed, monkeypatch):
    storage, index, _ = indexed
    filer = SnapshotFiler(memory_conn(), APP)
    filer.sync(index.refresh().snapshot())
    calls = []
    real = similar_filing.snapshot_facts
    monkeypatch.setattr(similar_filing, "snapshot_facts",
                        lambda snap, row: (calls.append(row["verstr"]), real(snap, row))[1])

    finished(storage, APP, verstr(3))  # a new run state, the same row
    snapshot = index.refresh().snapshot()
    filer.sync(snapshot)

    assert filer.synced_to(snapshot) and calls == []
    seed(storage, APP, verstr(RUNS), intent={"text": "new"})
    filer.sync(index.refresh().snapshot())
    assert calls == [verstr(RUNS)]
