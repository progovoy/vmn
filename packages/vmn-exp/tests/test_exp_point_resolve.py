"""Plan 25 F1: refs resolve as point reads on the persisted ``exp_rows`` —
an exact verstr, a unique prefix, ``@N`` and ``latest`` are each one indexed
query, never a snapshot of the app — and answer what the snapshot answers."""
import sqlite3

import pytest
from vmn_exp.core import index as experiment_index
from vmn_exp.core import index_store, sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_point import point_view
from vmn_exp.core.index_snapshot import IndexSnapshot, RowCache
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
RUNS = {  # verstr -> (second, parent)
    "0.0.1-dev.aaa1": (1, None),
    "0.0.1-dev.aaa2": (2, "0.0.1-dev.aaa1"),
    "0.0.1-dev.bbb1": (3, "0.0.1-dev.aaa2"),
    "0.0.2-dev.ccc1": (3, None),  # the same timestamp: ordered by name
}
REFS = [
    "0.0.1-dev.aaa1", "0.0.1-dev.aaa", "0.0.1-dev.b", "0.0.1-dev.zzz", "0.0.1-dev.",
    "@1", "@4", "@0", "@5", "@x", "latest", "@latest", "1.2.3", None,
]


def _save(st, verstr, second, parent=None):
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{second:02d}Z"}
    if parent:
        meta["parent"] = parent
    st.save(APP, verstr, meta, {})


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    for verstr, (second, parent) in RUNS.items():
        _save(st, verstr, second, parent)
    db = str(tmp_path / "idx.sqlite")
    index = ExperimentIndex(st, APP, cache_path=db)
    index.refresh()
    monkeypatch.setattr(LocalSnapshotStorage, "index_cache_path", lambda self, app: db)
    return st, db, index.snapshot()


def _no_snapshots(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("built a snapshot of the app")

    monkeypatch.setattr(RowCache, "snapshot", refuse)
    monkeypatch.setattr(IndexSnapshot, "build", refuse)
    monkeypatch.setattr(ExperimentIndex, "refresh", refuse)
    monkeypatch.setattr(ExperimentIndex, "_refresh_locked", refuse)
    monkeypatch.setattr(index_store, "decode_records", refuse)
    monkeypatch.setattr(experiment_index, "_SHARED", {})  # a fresh process


@pytest.mark.parametrize("ref", REFS)
def test_resolve_one_answers_what_the_snapshot_answers(indexed, ref):
    _, db, snap = indexed
    got = SqliteStore(db).resolve_one(APP, ref)
    want = snap.resolve(ref, kind="experiment")
    assert got == want
    if want[1] is not None:
        assert got[1].code == want[1].code


def test_latest_of_an_empty_app(tmp_path):
    db = str(tmp_path / "idx.sqlite")
    _, err = SqliteStore(db).resolve_one(APP, "latest")
    assert err == "No experiments found for app"


def test_each_point_query_uses_an_index(indexed, monkeypatch):
    _, db, _ = indexed
    statements = []
    connect = index_store.connect

    def tracing(path, **kwargs):
        conn = connect(path, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(index_store, "connect", tracing)
    store = SqliteStore(db)
    for ref in REFS:
        store.resolve_one(APP, ref)
    for verstr in RUNS:
        store.lean_row_of(APP, verstr), store.parent_of(APP, verstr)
        store.children_of(APP, verstr)
    plans = sqlite3.connect(sqlite_files.live_path(db))
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")
               and "exp_rows" in s and "COUNT(" not in s]  # COUNT: an out-of-range @N
    assert selects
    for statement in selects:
        plan = [row[-1] for row in plans.execute(f"EXPLAIN QUERY PLAN {statement}")]
        walks = [step for step in plan if _walks_the_app(step, statement)]
        assert not walks, (statement, plan)


def _walks_the_app(step, statement):
    """Whether a query plan *step* reads every row of the app: a scan, or an
    index searched on the app alone (but MAX's one seek)."""
    if step.startswith("SCAN") and "exp_rows" in step:
        return True
    seek = "MAX(timestamp)" in statement and "COVERING INDEX exp_rows_timestamp" in step
    return step.endswith("(app=?)") and not seek


def test_the_point_view_places_a_run_without_a_snapshot(indexed, monkeypatch):
    st, _, snap = indexed
    _no_snapshots(monkeypatch)
    view = point_view(st, APP)
    assert view.row("0.0.1-dev.aaa2")["idx"] == snap.row("0.0.1-dev.aaa2")["idx"] == 2
    assert view.parent_of.get("0.0.1-dev.bbb1") == "0.0.1-dev.aaa2"
    assert view.children_of.get("0.0.1-dev.aaa1", []) == ["0.0.1-dev.aaa2"]
    assert view.children_of.get("0.0.2-dev.ccc1", []) == []


def test_the_point_view_learns_runs_created_since_the_last_refresh(indexed, monkeypatch):
    st, _, _ = indexed
    _save(st, "0.0.3-dev.ddd1", 9, parent="0.0.1-dev.aaa1")
    _no_snapshots(monkeypatch)
    view = point_view(st, APP)
    assert view.resolve("@5") == ("0.0.3-dev.ddd1", None)
    assert view.resolve("latest") == ("0.0.3-dev.ddd1", None)
    assert view.children_of.get("0.0.1-dev.aaa1", []) == ["0.0.1-dev.aaa2", "0.0.3-dev.ddd1"]


def test_the_point_view_forgets_removed_runs(indexed, monkeypatch):
    st, _, _ = indexed
    st.delete(APP, "0.0.2-dev.ccc1")
    _no_snapshots(monkeypatch)
    view = point_view(st, APP)
    assert view.row("0.0.2-dev.ccc1") is None
    assert view.resolve("@4")[1] == "Index '@4' out of range (1..3)"


def test_resolve_experiment_needs_no_snapshot_once_indexed(indexed, monkeypatch):
    st, _, _ = indexed
    _no_snapshots(monkeypatch)
    assert resolve_experiment(st, APP, "@3") == ("0.0.1-dev.bbb1", None)
    assert resolve_experiment(st, APP, "0.0.1-dev.b") == ("0.0.1-dev.bbb1", None)
    # A tie on the newest timestamp: the first in storage order, as a snapshot answers.
    assert resolve_experiment(st, APP, None, latest=True) == ("0.0.1-dev.bbb1", None)


def test_a_cold_app_still_resolves_through_the_index(tmp_path, monkeypatch):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    _save(st, "0.0.1-dev.aaa1", 1)
    db = str(tmp_path / "idx.sqlite")
    monkeypatch.setattr(LocalSnapshotStorage, "index_cache_path", lambda self, app: db)
    assert point_view(st, APP) is None  # never indexed: the caller builds the index
    assert resolve_experiment(st, APP, "@1") == ("0.0.1-dev.aaa1", None)
    assert point_view(st, APP).resolve("@1") == ("0.0.1-dev.aaa1", None)
