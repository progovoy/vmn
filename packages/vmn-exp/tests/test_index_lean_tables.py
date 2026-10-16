"""Plan 25 F1: the persisted lean tables (``exp_rows`` + ``exp_sides``) hold
exactly what :func:`lean_row` derives from each record — after a full build,
an incremental refresh, a removal and a rewind, in-process or through the
I/O helper."""
import json
import sqlite3

import pytest
from vmn_exp.core import sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_views import SIDE_TABLES, lean_row
from vmn_exp.core.tree import ancestors
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"
FAILED = "state: finished\nexit_code: 1\n"
R = [f"0.0.1-dev.abc.r{i}" for i in range(6)]


def _ts(second):
    return f"2026-01-01T00:00:{second:02d}Z"


def _entry(st, verstr, kind, second, **fields):
    st.append_log_entry(APP, verstr, "w", {"timestamp": _ts(second), "type": kind, **fields})


def _run(st, verstr, second, state=None, **meta):
    st.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(second), **meta}, {})
    if state:
        st.save_file(APP, verstr, "run_state.yml", state)


def _seed(st):
    _run(st, R[0], 10, FINISHED, name="first")
    _entry(st, R[0], "create", 10, params={"lr": 0.1}, hypothesis="focal loss helps")
    _entry(st, R[0], "features", 11, features_version=1, source="capture",
           author={"writer": "w", "git_user_email": "a@x.io"}, changed={"files": ["a.py"]})
    _entry(st, R[0], "intent", 12, text="try focal loss", keywords=["focal"], source="user")
    _entry(st, R[0], "define_metric", 12, name="loss", goal="min")
    for step, loss in enumerate((0.9, 0.5)):
        _entry(st, R[0], "metrics", 13 + step, step=step, values={"loss": loss})
    _entry(st, R[0], "image", 15, name="x", step=0, path="media/x/0.png",
           sha256="ab" * 32, size=7)
    _run(st, R[1], 20, FAILED, parent=R[0], note="a child")
    _entry(st, R[1], "metrics", 21, values={"loss": 0.4})
    _run(st, R[2], 30, parent=R[1])
    _run(st, R[3], 40, FINISHED, name="lone", archived=True)


def _persisted(db):
    conn = sqlite3.connect(sqlite_files.live_path(db))
    try:
        rows = conn.execute(
            "SELECT key, idx, status, parent, root, timestamp, name, archived, row"
            " FROM exp_rows WHERE app = ?", (APP,)
        ).fetchall()
        sides = conn.execute(
            "SELECT key, kind, data FROM exp_sides WHERE app = ?", (APP,)
        ).fetchall()
    finally:
        conn.close()
    out = {
        key: {"columns": (idx, status, parent, root, ts, name, bool(archived)),
              "row": dict(json.loads(row), idx=idx), "sides": {}}
        for key, idx, status, parent, root, ts, name, archived, row in rows
    }
    for key, kind, data in sides:
        out[key]["sides"][kind] = json.loads(data)
    return out


def _normal(value):
    return json.loads(json.dumps(value, default=str))


def _expected(index):
    snap = index.snapshot()
    out = {}
    for key, record in index.records.items():
        meta = record["meta"]
        if meta is None:
            continue
        verstr = meta["verstr"]
        idx = snap.row(verstr)["idx"]
        row, note, *values = lean_row(idx, meta, record["fold"])
        chain = ancestors(verstr, snap.edges)
        sides = {name: v for name, v in zip(SIDE_TABLES, values) if v}
        if note is not None:
            sides["create_note"] = note
        out[key] = {
            "columns": (idx, snap.status_of(verstr), row.get("parent"),
                        chain[-1] if chain else None, row["timestamp"], row.get("name"),
                        row["archived"]),
            "row": _normal(row), "sides": _normal(sides),
        }
    return out


def _check(index, db):
    assert _persisted(db) == _expected(index)


@pytest.fixture(params=["in_process", "io_process"])
def index_of(request, tmp_path):
    made = []

    def make(st, db):
        index = ExperimentIndex(st, APP, cache_path=db)
        if request.param == "io_process" and not index.use_io_process():
            pytest.skip("no I/O helper process here")
        made.append(index)
        return index

    yield make
    for index in made:
        index.close()


def test_the_lean_tables_follow_every_change(tmp_path, index_of):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    _seed(st)
    db = str(tmp_path / "idx.sqlite")
    index = index_of(st, db)
    index.refresh()
    _check(index, db)

    # Incremental: a repeated metric, a run sorted into the middle, a
    # re-described record, a new child, a run state.
    _entry(st, R[2], "metrics", 31, values={"loss": 0.3})
    _entry(st, R[2], "metrics", 32, values={"loss": 0.2})
    _run(st, R[4], 15, FINISHED)
    _run(st, R[3], 40, FINISHED, name="renamed", note="now visible")
    _run(st, R[5], 50, parent=R[3])
    st.save_file(APP, R[2], "run_state.yml", FINISHED)
    index.refresh()
    _check(index, db)

    # Removal of a run in the middle of a chain: its child's root moves.
    st.delete(APP, R[1])
    index.refresh()
    _check(index, db)
    assert R[1] not in _persisted(db)

    # A rewind refolds the run.
    _entry(st, R[0], "metrics", 16, step=2, values={"loss": 0.1})
    _entry(st, R[0], "rewind", 17, step=0)
    index.refresh()
    _check(index, db)


def test_a_restarted_index_keeps_the_tables_equal(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    _seed(st)
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()

    _entry(st, R[1], "metrics", 22, values={"loss": 0.35})
    _run(st, R[4], 5)
    restarted = ExperimentIndex(st, APP, cache_path=db)
    restarted.refresh()
    _check(restarted, db)
