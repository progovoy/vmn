"""Plan 25 F3: SqliteStore generations, delta reads and schema handling."""
import logging
import os
import sqlite3
import subprocess
import sys

import pytest

from exp_helpers import _SRC_PATH
from vmn_exp.core import index_store_schema
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.index_store_schema import SCHEMA_VERSION, RecordsOutdated, ensure_schema
from vmn_exp.core.sqlite_conn import connect

APP = "app"


def _rec(verstr):
    return {"verstr": verstr, "meta": {"verstr": verstr}}


_SAVER = """
import sys
from vmn_exp.core.index_store import SqliteStore
path, name, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
store = SqliteStore(path)
for i in range(n):
    assert store.save("app", {f"{name}-{i}": {"verstr": str(i)}}, set()) is not False
"""


def test_two_processes_saving_concurrently_never_reuse_a_generation(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, {"seed": _rec("0")}, set())
    env = dict(os.environ, PYTHONPATH=_SRC_PATH)
    n, procs = 150, 3
    children = [
        subprocess.Popen([sys.executable, "-c", _SAVER, path, f"p{k}", str(n)], env=env)
        for k in range(procs)
    ]
    assert [c.wait(120) for c in children] == [0] * procs
    conn = sqlite3.connect(path)
    seqs = [seq for (seq,) in conn.execute("SELECT seq FROM exp_index WHERE app = ?", (APP,))]
    assert len(seqs) == len(set(seqs)) == n * procs + 1
    assert SqliteStore(path).generation(APP) == n * procs + 1


def _traced(store):
    statements = []
    store._conn.set_trace_callback(statements.append)
    return statements


def test_a_delta_reads_only_the_changed_records(tmp_path):
    store = SqliteStore(str(tmp_path / "idx.sqlite"))
    store.save(APP, {f"k{i}": _rec(str(i)) for i in range(50)}, set())
    gen = store.generation(APP)
    store.save(APP, {f"k{i}": _rec(f"new{i}") for i in range(3)}, set(),
               {"k0": {"rs_sig": "s", "run_state": {"state": "running"}}})
    statements = _traced(store)
    changed, removed, new_gen = store.load_since(APP, gen)
    assert set(changed) == {"k0", "k1", "k2"} and removed == set()
    assert changed["k0"]["run_state"] == {"state": "running"}
    assert new_gen == gen + 1
    reads = [s for s in statements if "data" in s and s.lstrip().upper().startswith("SELECT")]
    assert reads and all(" IN (" in s for s in reads), reads


def test_a_large_delta_reads_in_chunks(tmp_path):
    store = SqliteStore(str(tmp_path / "idx.sqlite"))
    store.save(APP, {f"k{i}": _rec(str(i)) for i in range(1300)}, set())
    gen = store.generation(APP)
    store.save(APP, {f"k{i}": _rec(f"new{i}") for i in range(1200)}, set())
    statements = _traced(store)
    changed, _, _ = store.load_since(APP, gen)
    assert len(changed) == 1200
    reads = [s for s in statements if "FROM exp_index " in s and "data" in s]
    assert len(reads) == 3, reads


def test_delta_key_scans_use_the_seq_index(tmp_path):
    store = SqliteStore(str(tmp_path / "idx.sqlite"))
    for table in ("exp_index", "exp_index_state", "exp_index_tombstones"):
        plan = store._conn.execute(
            f"EXPLAIN QUERY PLAN SELECT key FROM {table} WHERE app = ? AND seq > ?", (APP, 0)
        ).fetchall()
        assert any("INDEX" in row[-1] and "seq" in row[-1] for row in plan), (table, plan)


def test_seq_precedes_data(tmp_path):
    store = SqliteStore(str(tmp_path / "idx.sqlite"))
    for table in ("exp_index", "exp_index_state"):
        cols = [row[1] for row in store._conn.execute(f"PRAGMA table_info({table})")]
        assert cols.index("seq") < cols.index("data"), cols


def test_a_store_ahead_of_its_file_reloads_fully(tmp_path):
    """A follower's generation past the file's (the file was rebuilt) is a full load."""
    store = SqliteStore(str(tmp_path / "idx.sqlite"))
    store.save(APP, {"a": _rec("1")}, set())
    changed, removed, gen = store.load_since(APP, 57)
    assert set(changed) == {"a"} and removed is None and gen == 1


def _set_schema(path, version):
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'schema'", (version,))
    conn.commit()
    conn.close()


def _newer():
    prefix, number = SCHEMA_VERSION.rsplit("-", 1)
    return f"{prefix}-{int(number) + 1}"


def test_a_newer_schema_is_left_alone_and_warned_about_once(tmp_path, caplog):
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, {"a": _rec("1")}, set())
    _set_schema(path, _newer())
    caplog.set_level(logging.WARNING)
    for _ in range(2):
        store = SqliteStore(path)
        assert store.load(APP) == {}
        assert store.save(APP, {"b": _rec("2")}, set()) is False
    warnings = [r for r in caplog.records if path in r.getMessage()]
    assert len(warnings) == 1 and "newer" in warnings[0].getMessage()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT v FROM exp_index_meta").fetchone()[0] == _newer()
    assert conn.execute("SELECT key FROM exp_index").fetchall() == [("a",)]


def test_an_older_schema_is_left_untouched_for_a_new_generation(tmp_path):
    # A file of older records is never dropped in place (a 13 GB DROP held the
    # write lock for minutes and wiped a multi-hour index): ensure_schema
    # refuses it, writing nothing, and the upgrade builds a new generation.
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, {"a": _rec("1")}, set())
    _set_schema(path, "exp-index-1")
    conn = connect(path)
    statements = []
    conn.set_trace_callback(statements.append)
    with pytest.raises(RecordsOutdated):
        ensure_schema(conn)
    assert not [s for s in statements if not s.lstrip().upper().startswith("SELECT")]
    assert conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()[0] == "exp-index-1"
    assert conn.execute("SELECT COUNT(*) FROM exp_index").fetchone()[0] == 1


def test_a_current_schema_opens_without_writing(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path)
    conn = connect(path)
    statements = []
    conn.set_trace_callback(statements.append)
    ensure_schema(conn)
    assert not [s for s in statements if not s.lstrip().upper().startswith("SELECT")]


def test_schema_numbers_compare_numerically():
    assert index_store_schema.is_newer("exp-index-100", "exp-index-99")
    assert not index_store_schema.is_newer("exp-index-9", "exp-index-13")
    assert not index_store_schema.is_newer("garbage", "exp-index-13")
