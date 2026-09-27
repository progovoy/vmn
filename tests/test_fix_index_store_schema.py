"""IndexStore: corruption-after-open reset.

P0.3 (reduced scope): a database that becomes corrupt after opening resets/
rebuilds instead of raising.  A transient OperationalError (e.g. locked DB)
must NOT trigger a reset.
"""
import sqlite3

import pytest

from vmn_exp.core.index_store import IndexStore

APP = "myapp"


# ---------------------------------------------------------------------------
# test_corrupt_after_open_rebuilds
# ---------------------------------------------------------------------------

def test_corrupt_after_open_rebuilds(tmp_path, monkeypatch):
    """A database that turns corrupt AFTER IndexStore.__init__ succeeds must be
    detected on the first read, reset, and leave the store fully usable.

    The corruption is simulated by injecting sqlite3.DatabaseError (exact base
    type, not a subclass — SQLITE_CORRUPT maps to the base DatabaseError in
    CPython's sqlite3 module) on the first _select call.
    """
    store = IndexStore(str(tmp_path / "idx.sqlite"))
    assert store._conn is not None

    store.save(APP, {"before": {"verstr": "0.0.1"}}, set(), {})

    real_select = IndexStore._select
    fired = [False]

    def corrupt_once(self, table, app_name):
        if not fired[0]:
            fired[0] = True
            raise sqlite3.DatabaseError("database disk image is malformed")
        return real_select(self, table, app_name)

    monkeypatch.setattr(IndexStore, "_select", corrupt_once)

    # load() must not raise; it detects corruption, resets, and returns {}
    result = store.load(APP)
    assert result == {}, "corrupt-after-open load must return empty dict, not raise"

    # After the reset the store must be fully usable again
    store.save(APP, {"after_reset": {"verstr": "0.0.2"}}, set(), {})
    result2 = store.load(APP)
    assert "after_reset" in result2, "store must be usable after corruption reset"


# ---------------------------------------------------------------------------
# test_operational_error_does_not_reset
# ---------------------------------------------------------------------------

def test_operational_error_does_not_reset(tmp_path, monkeypatch):
    """A transient OperationalError (e.g. locked DB, disk-full) on read must
    NOT wipe/reset the store — only plain DatabaseError (SQLITE_CORRUPT)
    triggers a rebuild.
    """
    store = IndexStore(str(tmp_path / "idx.sqlite"))
    store.save(APP, {"row": {"verstr": "1.0.0"}}, set(), {})

    original_conn = store._conn
    real_select = IndexStore._select
    fired = [False]

    def locked_once(self, table, app_name):
        if not fired[0]:
            fired[0] = True
            raise sqlite3.OperationalError("database is locked")
        return real_select(self, table, app_name)

    monkeypatch.setattr(IndexStore, "_select", locked_once)

    # load() returns {} on OperationalError (skips the data gracefully)
    result = store.load(APP)
    assert result == {}

    # The connection must NOT have been replaced — no reset happened
    assert store._conn is original_conn, (
        "OperationalError must not trigger a reset; connection was replaced"
    )

    # The store is still fully usable — data persists for the next read
    result2 = store.load(APP)
    assert "row" in result2
