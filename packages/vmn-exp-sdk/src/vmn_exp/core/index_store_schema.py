#!/usr/bin/env python3
"""Tables of :class:`vmn_exp.core.index_store.SqliteStore`.

``seq`` stamps each row with the scope generation that last wrote it (indexed
with the app, and stored before the JSON so a key scan never walks past it);
``exp_index_gen`` holds a scope's generation and its tombstone ``horizon``
(the newest trimmed tombstone's seq — a follower behind it needs a full load).

A record is stored as its ``head`` (everything but its fold and run state:
the signatures a refresh compares) and its ``data`` (the fold). What readers
read of it is persisted beside it in the same transaction (plan 25 §2): its
lean row in ``exp_rows`` — the columns ``list`` sorts and filters on as real
columns — and its side table values in ``exp_sides``, one row per non-empty
``kind`` (see :mod:`vmn_exp.core.index_lean_store`), and its similar-runs
document in the ``similar_*`` tables (:mod:`vmn_exp.core.similar_fts`).

Two versions, so an upgrade never costs more than it must:

- :data:`RECORDS_VERSION` covers what was read from storage — the records,
  run states, tombstones, generations and key-values (listing baselines,
  journal marks): re-reading them costs hours of S3 reads at 500k runs. Bump
  it when a record's shape, the fold's semantics or the run state change so
  that an older record cannot be trusted. :func:`ensure_schema` refuses a
  file of older records, writing nothing; :mod:`vmn_exp.core.index_store_upgrade`
  upgrades it in place when their version is in :data:`COPYABLE_RECORDS`
  (they still read right), else builds a new generation file beside it,
  loaded afresh from storage. A change that leaves most records right lists
  the older version there with a predicate picking the others: they alone
  are read again (records 18: runs with a name both a param and a logged
  metric). One whose records may be wrong but rarely are lists a predicate
  in :data:`CHECKED_RECORDS`: those it picks are checked cheaply in the
  background, read again only when they must be (records 18 and 19: runs
  with compacted metrics logged more than once).
- :data:`DERIVED_VERSION` covers the tables derived purely from the records
  (``exp_rows``, ``exp_sides``, ``similar_*``). Bump it when what is derived
  changes (lean rows, side values, statuses, similar documents) or a derived
  table gains a column. An older file is upgraded in place by one short
  transaction — missing tables created, each app marked to re-derive
  (:mod:`vmn_exp.core.index_derive`) — never a drop: its records, journal
  mark and baselines stay, and each app's index re-derives its rows locally,
  serving the old ones meanwhile, ``loading`` (:data:`KEPT_SCOPE`). A new derived column is an ``ALTER TABLE ... ADD
  COLUMN`` there; a dropped or retyped one needs a new table name.

A records bump bumps :data:`DERIVED_VERSION` too. The ``schema`` meta value
is :data:`SCHEMA_VERSION` (``exp-index-<derived>``), what vmn-exp read before
this split (it leaves a file with a newer one alone); ``records`` is
``<records>/<schema>``, trusted only beside the schema it was written with
(an older vmn-exp rewriting the schema leaves it stale). Without it, a file of
``exp-index-N`` holds records ``min(N, 18)``: exp-index-19 changed only
derived tables.
"""
import sqlite3

from vmn_exp.core import similar_fts
from vmn_exp.core.fold import logged_params
from vmn_exp.core.index_store_kv import write_puts
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.core.metric_summary import is_repeated
from vmn_exp.core.sqlite_conn import write_tx

RECORDS_VERSION = 20  # 20: step restarts; a .vmx's first/last write (vmx_write_order)
DERIVED_VERSION = 21  # 21: rows' metric_policy, an empty summary missing (plan 32 F1)
SCHEMA_VERSION = f"exp-index-{DERIVED_VERSION}"


def _param_logged_too(fold):
    """Whether *fold* has a name both a param and a logged metric: records 18
    may hold the param's number over the metric (plan 32 F8)."""
    return bool(logged_params(fold))


def _compacted_logged_twice(head, fold):
    """Whether the record of *head* folded ``.vmx`` objects and its *fold* a
    metric logged more than once: records 19 folded from an older ``.vmx``
    footer may hold such a metric's value at its highest step for its last
    write, and lack its step restart. The fold does not say which metric
    came from which file; the head's metric objects say a ``.vmx`` was read."""
    objects = ((head.get("metrics") or {}).get("objects") or {})
    return (any(is_indexed_file(name) for name in objects)
            and any(is_repeated(seen) for seen in (fold.get("extrema") or {}).values()))


# Older records versions whose records still read right in this one, each with
# None or a predicate of a record's fold: True when that record does not and
# is read again from storage instead (see index_store_upgrade).
COPYABLE_RECORDS = {18: _param_logged_too, 19: None}
# Of those, the ones whose records may not read right, each with a predicate
# of a record's head and fold: True when that record is checked in the
# background (vmx_check, index_vmx_check), folded again only when it must be.
CHECKED_RECORDS = {18: _compacted_logged_twice, 19: _compacted_logged_twice}
_LEGACY_RECORDS = 18  # the newest records of a file with no "records" meta value
NEW, DERIVED = "new", "derived"  # the upgrades ensure_schema makes
DERIVE_SCOPE = "derive:"  # exp_index_kv scope prefix of an app left to re-derive
# exp_index_kv scope, fingerprint SCHEMA_VERSION: the re-derive at this schema
# rewrites rows an in-place upgrade kept, served (stale) meanwhile.
KEPT_SCOPE = "kept-rows"

RECORD_TABLES = {
    "exp_index": "app TEXT, key TEXT, seq INTEGER, head TEXT, data TEXT,"
                 " PRIMARY KEY (app, key)",
    "exp_index_state": "app TEXT, key TEXT, seq INTEGER, data TEXT, PRIMARY KEY (app, key)",
    "exp_index_tombstones": "app TEXT, key TEXT, seq INTEGER, ts REAL, PRIMARY KEY (app, key)",
    "exp_index_gen": "app TEXT PRIMARY KEY, gen INTEGER, horizon INTEGER",
    "exp_index_kv": "scope TEXT PRIMARY KEY, fingerprint TEXT, payload TEXT",
}
_DERIVED_TABLES = {
    "exp_rows": "app TEXT, key TEXT, verstr TEXT, idx INTEGER, status TEXT, parent TEXT,"
                " root TEXT, timestamp TEXT, name TEXT, archived INTEGER, seq INTEGER,"
                " row TEXT, PRIMARY KEY (app, key)",
    "exp_sides": "app TEXT, key TEXT, kind TEXT, data TEXT, PRIMARY KEY (app, key, kind)",
}
_SEQ_INDEXED = ("exp_index", "exp_index_state", "exp_index_tombstones")
_ROW_INDEXES = {
    "idx": "idx", "status": "status", "parent": "parent", "root": "root",
    "timestamp": "timestamp, key", "verstr": "verstr",
}


class SchemaTooNew(Exception):
    """The file was written by a newer vmn-exp: leave it to that version."""


class RecordsOutdated(Exception):
    """The file holds records of an older :data:`RECORDS_VERSION` (``found``;
    None: unknown)."""

    def __init__(self, found):
        super().__init__(f"records version {found}")
        self.found = found


def _number(version):
    prefix, _, number = (version or "").rpartition("-")
    return int(number) if prefix == "exp-index" and number.isdigit() else None


def is_newer(found, ours=SCHEMA_VERSION):
    """Whether the schema *found* in a file is newer than *ours*."""
    found_n, ours_n = _number(found), _number(ours)
    return found_n is not None and ours_n is not None and found_n > ours_n


def records_mark():
    """The ``records`` meta value this version writes."""
    return f"{RECORDS_VERSION}/{SCHEMA_VERSION}"


def records_version(schema, mark):
    """The records version of a cache whose ``schema`` and ``records`` meta
    values are these (see the module); None when unknown."""
    held, _, written_with = (mark or "").partition("/")
    if written_with == schema and held.isdigit():
        return int(held)
    number = _number(schema)
    return None if number is None else min(number, _LEGACY_RECORDS)


def _meta(conn):
    try:
        return dict(conn.execute("SELECT k, v FROM exp_index_meta").fetchall())
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None  # a new file
        raise


def upgrade_of(conn):
    """What :func:`ensure_schema` makes of the file: :data:`NEW`,
    :data:`DERIVED` or None (current); raises :class:`SchemaTooNew` or
    :class:`RecordsOutdated`."""
    meta = _meta(conn)
    if meta is None:
        return NEW
    schema = meta.get("schema")
    records, derived = records_version(schema, meta.get("records")), _number(schema)
    if (derived or 0) > DERIVED_VERSION or (records or 0) > RECORDS_VERSION:
        raise SchemaTooNew(schema)
    if derived is None or records != RECORDS_VERSION:
        raise RecordsOutdated(records)
    return DERIVED if derived < DERIVED_VERSION else None


def ensure_schema(conn):
    """Bring the file to this version without rewriting a row of it: a new
    file gets its tables, an older derived version is marked to re-derive —
    one short transaction either way, none for a current file. Raises
    :class:`SchemaTooNew` or :class:`RecordsOutdated` (see the module)."""
    if upgrade_of(conn) is None:
        return
    with write_tx(conn):
        upgrade = upgrade_of(conn)  # another process may have just done it
        if upgrade == NEW:
            _create(conn)
        elif upgrade == DERIVED:
            upgrade_derived(conn, kept=True)


def upgrade_derived(conn, kept=False):
    """In the caller's write transaction: bring the derived tables to this
    version (each app marked to re-derive) and write the versions; *kept*:
    the rows are kept to serve until re-derived (:data:`KEPT_SCOPE`)."""
    _create_derived(conn)
    mark_derive_pending(conn)
    if kept:
        write_puts(conn, [(KEPT_SCOPE, SCHEMA_VERSION, True)])
    _write_versions(conn)


def _create(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS exp_index_meta (k TEXT PRIMARY KEY, v TEXT)")
    for table, columns in RECORD_TABLES.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
    for table in _SEQ_INDEXED:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_seq ON {table} (app, seq)")
    _create_derived(conn)
    _write_versions(conn)


def _create_derived(conn):
    for table, columns in _DERIVED_TABLES.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
    for name, columns in _ROW_INDEXES.items():
        conn.execute(f"CREATE INDEX IF NOT EXISTS exp_rows_{name} ON exp_rows (app, {columns})")
    similar_fts.create_tables(conn)


def _write_versions(conn):
    conn.executemany(
        "INSERT INTO exp_index_meta (k, v) VALUES (?, ?)"
        " ON CONFLICT (k) DO UPDATE SET v = excluded.v",
        [("schema", SCHEMA_VERSION), ("records", records_mark())],
    )


def mark_derive_pending(conn):
    """Leave every app the file holds to re-derive from its first record."""
    write_puts(conn, [(DERIVE_SCOPE + app, SCHEMA_VERSION, {"after": ""})
                      for (app,) in conn.execute("SELECT app FROM exp_index_gen").fetchall()])
