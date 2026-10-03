#!/usr/bin/env python3
"""Tables of :class:`vmn_exp.core.index_store.SqliteStore`.

``seq`` stamps each row with the scope generation that last wrote it;
``exp_index_gen`` holds a scope's generation and its tombstone ``horizon`` (the
newest trimmed tombstone's seq — a follower behind it needs a full load).
"""

# Bump whenever a record's shape, the fold's semantics or these tables change:
# records written by another version are dropped rather than trusted.
SCHEMA_VERSION = "exp-index-11"

_TABLES = {
    "exp_index": "app TEXT, key TEXT, data TEXT, seq INTEGER, PRIMARY KEY (app, key)",
    "exp_index_state": "app TEXT, key TEXT, data TEXT, seq INTEGER, PRIMARY KEY (app, key)",
    "exp_index_tombstones": "app TEXT, key TEXT, seq INTEGER, ts REAL, PRIMARY KEY (app, key)",
    "exp_index_gen": "app TEXT PRIMARY KEY, gen INTEGER, horizon INTEGER",
    "exp_index_kv": "scope TEXT PRIMARY KEY, fingerprint TEXT, payload TEXT",
}


def ensure_schema(conn):
    """Create the tables; drop them first when written by another schema."""
    conn.execute("CREATE TABLE IF NOT EXISTS exp_index_meta (k TEXT PRIMARY KEY, v TEXT)")
    row = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    if not row or row[0] != SCHEMA_VERSION:
        for table in _TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(
            "INSERT OR REPLACE INTO exp_index_meta (k, v) VALUES ('schema', ?)",
            (SCHEMA_VERSION,),
        )
    for table, columns in _TABLES.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
    conn.commit()
