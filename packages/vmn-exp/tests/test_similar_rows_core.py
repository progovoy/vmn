"""The runs a similar-runs query reads besides its FTS table
(vmn_exp.core.similar_rows): from an index snapshot, or point reads on the
persisted index — the same answers either way."""
import sqlite3

import pytest
from similar_fixtures import FakeSnapshot, run
from similar_seed import features, finished, seed, verstr
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.similar_rows import SnapshotRows, StoreRows
from vmn_exp.snapshot import open_storage

APP = "trainer"


@pytest.fixture
def both(tmp_path):
    storage = open_storage(root=str(tmp_path / "store"), area="runs")
    outer = seed(storage, APP, verstr(1), name="outer", note="sweep")
    inner = seed(storage, APP, verstr(2), parent=outer, intent={"text": "focal"},
                 changes=features(["a.py"]), goal=("loss", "min"), metrics={"loss": 1.0})
    deeper = seed(storage, APP, verstr(3), parent=inner)
    seed(storage, APP, verstr(4))
    finished(storage, APP, inner, exit_code=1)
    path = str(tmp_path / "index.sqlite")
    index = ExperimentIndex(storage, APP, path, full_sweep_sec=0)
    snapshot = index.refresh().snapshot()
    conn = sqlite3.connect(path, isolation_level=None)
    return (SnapshotRows(snapshot), StoreRows(conn, APP)), (outer, inner, deeper, verstr(4))


def test_both_sources_answer_alike(both):
    sources, (outer, inner, deeper, single) = both
    answers = []
    for rows in sources:
        got = rows.rows_of([outer, inner, deeper, single, "missing"])
        answers.append((
            sorted(got), got[inner]["name"], got[inner]["parent"],
            [rows.root(got[v]) for v in (outer, inner, deeper, single)],
            rows.root({"verstr": "new", "parent": deeper}),
            rows.parents_among([outer, inner, deeper, single]),
            rows.status_of(inner), rows.status_of(single),
            rows.facts(got[inner])[:2], rows.declared_schema(),
        ))
    assert answers[0] == answers[1]
    assert answers[0][3] == [outer, outer, outer, single]
    assert answers[0][4] == outer
    assert answers[0][5] == {outer, inner}
    assert answers[0][6:8] == ("failed", "created")
    assert answers[0][8][1]["text"] == "focal"
    assert answers[0][9] == {"loss": {"goal": "min"}}


def test_a_snapshot_without_side_tables_reads_none():
    rows = SnapshotRows(FakeSnapshot([run("a")]))
    assert rows.facts(rows.row("a")) == (None, None, None, None, None)
    assert rows.row("missing") is None and rows.status_of("a") == "created"


def test_a_run_state_command_stands_in_for_the_rows():
    snap = FakeSnapshot([run("a")], run_states={"a": {"command": ["python", "x.py"]}})
    rows = SnapshotRows(snap)
    assert rows.facts(rows.row("a"))[3] == ["python", "x.py"]
