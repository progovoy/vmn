"""A SqliteStore's one connection is shared by the index's threads (a
refresher, request threads reading lazy records): its plain reads take turns
with its transactions under the connection's lock. macOS's SQLite does not
serialize two threads on one connection itself: unserialized, they spun
forever in its page cache or aborted the process."""
import threading

from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.sqlite_conn import write_tx


def test_a_read_waits_for_a_transaction_on_the_shared_connection(tmp_path):
    store = SqliteStore(str(tmp_path / "idx.sqlite"))
    conn, _ = store.connection()
    in_tx, release, read = threading.Event(), threading.Event(), threading.Event()

    def writer():
        with write_tx(conn):
            in_tx.set()
            release.wait(5)

    def reader():
        store.load("app")
        read.set()

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    threads[0].start()
    assert in_tx.wait(5)
    threads[1].start()
    assert not read.wait(0.3)  # waits for the transaction
    release.set()
    for thread in threads:
        thread.join(10)
    assert read.is_set()
    store.close()
