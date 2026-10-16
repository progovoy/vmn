"""One connection shared by a process's threads (index_point.shared_store):
transactions on it take turns instead of nesting."""
import threading

from vmn_exp.core.sqlite_conn import connect, read_tx, write_tx


def _transact(conn, kind, entered, release, errors):
    try:
        with kind(conn):
            entered.set()
            release.wait(5)
            if kind is write_tx:
                conn.execute("INSERT INTO t VALUES (1)")
    except Exception as exc:
        errors.append(exc)


def test_two_threads_transactions_on_one_connection_take_turns(tmp_path):
    conn = connect(str(tmp_path / "x.sqlite"))
    conn.execute("CREATE TABLE t (v)")
    errors = []
    first_in, release = threading.Event(), threading.Event()
    first = threading.Thread(target=_transact, args=(conn, read_tx, first_in, release, errors))
    first.start()
    first_in.wait(5)
    second_in, go = threading.Event(), threading.Event()
    go.set()
    second = threading.Thread(target=_transact, args=(conn, write_tx, second_in, go, errors))
    second.start()

    assert not second_in.wait(0.3)  # waits for the first transaction
    release.set()
    first.join(5)
    second.join(10)

    assert errors == []
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1
