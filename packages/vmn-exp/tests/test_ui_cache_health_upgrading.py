"""Plan 34 §4: while an upgrader holds ``<path>.upgrade`` the file still reads
as holding older records; the health probe must not take that for a schema
problem and start a full rebuild under the upgrade."""
import sqlite3

import pytest

pytest.importorskip("fastapi")
from filelock import FileLock  # noqa: E402

from vmn_exp.core import index_store_upgrade, sqlite_files  # noqa: E402
from vmn_exp.core.index_store import SqliteStore  # noqa: E402
from vmn_exp.ui.cache_health import SqliteHealth  # noqa: E402


@pytest.fixture
def outdated(tmp_path):
    db = str(tmp_path / "cache.sqlite")
    SqliteStore(db).close()
    conn = sqlite3.connect(sqlite_files.live_path(db))
    (schema,) = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'records'", (f"19/{schema}",))
    conn.commit()
    conn.close()
    return db


def test_older_records_are_a_schema_problem(outdated):
    assert SqliteHealth(outdated).problem() == "schema"


def test_older_records_under_an_upgrade_are_no_problem(outdated):
    health = SqliteHealth(outdated)
    with FileLock(outdated + index_store_upgrade.LOCK_SUFFIX):
        assert health.problem() is None
