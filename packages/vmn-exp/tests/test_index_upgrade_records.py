"""An upgrade of the stored records (``RECORDS_VERSION``) never drops them in
place on the live file: a new generation file is built beside it and the
pointer flipped to it (the old file is left untouched until then, and swept
once unused). Records still readable in the new format are copied over
locally, a chunk per transaction, instead of being re-read from storage."""
import sqlite3

from vmn_exp.core import index_store_schema, index_store_upgrade, sqlite_files
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index_store import SqliteStore

APP = "app"
OLD_RECORDS = "exp-index-10"  # a tag-only file of exp-index-10 holds records format 10


def _record(i):
    return {
        "meta_sig": None, "logs": {}, "counts": {}, "rs_sig": None,
        "meta": {"verstr": f"0.0.1-dev.a.{i}", "timestamp": f"2026-01-01T00:00:{i:02d}Z"},
        "fold": fold_log([]), "run_state": {"state": "finished", "exit_code": 0},
    }


def _old_file(tmp_path, n=3):
    path = str(tmp_path / "idx.sqlite")
    records = {f"k{i}": _record(i) for i in range(n)}
    store = SqliteStore(path)
    store.save(APP, records, set(), records)
    store.kv_put("journal-mark:app", "journal-mark-1", {"ms": 5})
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'schema'", (OLD_RECORDS,))
    conn.commit()
    conn.close()
    return path


def _state(file):
    conn = sqlite3.connect(file)
    try:
        return (conn.execute("SELECT COUNT(*) FROM exp_index").fetchone()[0],
                conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()[0])
    finally:
        conn.close()


def _spy_flip(monkeypatch, path):
    """``[(old file's (records, tag) when flipped, the file flipped to)]``."""
    seen, real = [], sqlite_files.flip

    def flip(logical, target):
        seen.append((_state(path), target))
        real(logical, target)

    monkeypatch.setattr(sqlite_files, "flip", flip)
    return seen


def test_older_records_go_to_a_new_generation_leaving_the_old_file_untouched(
        tmp_path, monkeypatch):
    path = _old_file(tmp_path)
    flips = _spy_flip(monkeypatch, path)
    store = SqliteStore(path)
    assert store.load(APP) == {}  # not readable in this format: loaded afresh
    [(old_at_flip, target)] = flips
    assert old_at_flip == (3, OLD_RECORDS)
    assert sqlite_files.live_path(path) == target != path
    assert _state(target)[1] == index_store_schema.SCHEMA_VERSION


def test_records_still_readable_are_copied_to_the_new_generation(tmp_path, monkeypatch):
    path = _old_file(tmp_path, n=7)
    monkeypatch.setattr(index_store_schema, "COPYABLE_RECORDS", frozenset({10}))
    monkeypatch.setattr(index_store_upgrade, "COPY_CHUNK", 2)
    flips = _spy_flip(monkeypatch, path)
    store = SqliteStore(path)
    [(old_at_flip, target)] = flips
    assert old_at_flip == (7, OLD_RECORDS)
    assert sorted(store.load(APP)) == [f"k{i}" for i in range(7)]
    assert store.kv_get("journal-mark:app", "journal-mark-1") == {"ms": 5}
    assert store.deriving(APP)
    store.derive(APP)
    assert not store.deriving(APP)
    conn = sqlite3.connect(target)
    assert conn.execute("SELECT key, idx FROM exp_rows ORDER BY idx").fetchall() == [
        (f"k{i}", i + 1) for i in range(7)]


def test_a_slow_open_of_one_index_file_never_holds_up_another(tmp_path, monkeypatch):
    import threading

    from vmn_exp.core import index_point

    slow, other = str(tmp_path / "slow.sqlite"), str(tmp_path / "other.sqlite")
    entered, release, real = threading.Event(), threading.Event(), index_point.IndexStore

    def opening(path):
        if path == slow:  # an upgrade copying records into a new generation
            entered.set()
            release.wait(10)
        return real(path)

    monkeypatch.setattr(index_point, "IndexStore", opening)
    opener = threading.Thread(target=lambda: index_point.shared_store(slow))
    opener.start()
    try:
        assert entered.wait(5)
        answered = []
        asker = threading.Thread(target=lambda: answered.append(index_point.shared_store(other)))
        asker.start()
        asker.join(2)
        assert answered, "shared_store waited for another file's open"
    finally:
        release.set()
        opener.join()
