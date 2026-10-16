#!/usr/bin/env python3
"""The tables similar runs search (plan 24 §3), in an index's SQLite file.

``similar_fts`` is an FTS5 table holding one document per run, one column per
signal (:data:`~vmn_exp.core.similar_doc.COLUMNS`; ``app`` and ``verstr``
unindexed: a file may hold several apps), ``similar_vocab`` its per-column
document frequencies and ``similar_doc`` what each run was filed with —
its raw tokens (for reasons), rerun key, command, profile version and a
signature of the whole, so refiling an unchanged document writes nothing.

What fills them is :mod:`vmn_exp.core.similar_filing`. FTS5 is required
(:func:`require_fts5`); without it the index works on and only similar runs
fail.
"""
import hashlib
import json
import sqlite3

from vmn_exp.core.similar_doc import COLUMNS, PROFILE_VERSION, Doc

TABLES = ("similar_fts", "similar_vocab", "similar_doc")
_CHUNK = 500  # keys per query, under SQLite's bound-parameter limit
_FTS5 = []  # [available] once checked


class Fts5Missing(RuntimeError):
    def __init__(self):
        super().__init__("similar runs need SQLite with FTS5 (python's sqlite3 lacks it)")


def fts5_available():
    if not _FTS5:
        try:
            sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            _FTS5.append(True)
        except sqlite3.Error:
            _FTS5.append(False)
    return _FTS5[0]


def require_fts5():
    if not fts5_available():
        raise Fts5Missing()


def _create(conn):
    exists = "IF NOT EXISTS "
    conn.execute(
        f"CREATE VIRTUAL TABLE {exists}similar_fts USING fts5(app UNINDEXED, verstr UNINDEXED, "
        + ", ".join(COLUMNS) + ", tokenize = 'porter unicode61')")
    conn.execute(f"CREATE VIRTUAL TABLE {exists}similar_vocab USING fts5vocab(similar_fts, 'col')")
    conn.execute(f"CREATE TABLE {exists}similar_doc (id INTEGER PRIMARY KEY, app TEXT, key TEXT,"
                 " verstr TEXT, rerun TEXT, cmd TEXT, version TEXT, sig TEXT, data TEXT,"
                 " UNIQUE (app, key))")
    conn.execute(f"CREATE INDEX {exists}similar_doc_verstr ON similar_doc (app, verstr)")
    conn.execute(f"CREATE INDEX {exists}similar_doc_version ON similar_doc (app, version)")


def create_tables(conn):
    """(Re)create the tables, empty — part of an index schema change; a
    no-op without FTS5."""
    if not fts5_available():
        return
    for table in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    _create(conn)


def ensure_tables(conn):
    require_fts5()
    if not has_tables(conn):  # never a write on a file that has them
        _create(conn)


def has_tables(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name IN (?, ?, ?)", TABLES
    ).fetchone()[0] == len(TABLES)


def chunks(items):
    items = list(items)
    for i in range(0, len(items), _CHUNK):
        yield items[i:i + _CHUNK]


def marks(chunk):
    return ", ".join("?" * len(chunk))


def filed(conn, app, keys, columns="id, sig, version"):
    """``{key: (columns...)}`` of *keys*' stored docs."""
    out = {}
    for chunk in chunks(keys):
        for key, *values in conn.execute(
                f"SELECT key, {columns} FROM similar_doc"
                f" WHERE app = ? AND key IN ({marks(chunk)})",
                (app, *chunk)):
            out[key] = values
    return out


def _cmd(command):
    return json.dumps(command, default=str)


def file_docs(conn, app, entries, commands=None):
    """File *entries* — ``[(key, Doc)]`` — of *app*, replacing each key's
    earlier document unless it is the same; *commands* ``{key: argv}`` are
    stored as the commands they were filed with."""
    entries = list(entries)
    if not entries:
        return
    commands = commands or {}
    known = filed(conn, app, [key for key, _ in entries])
    for key, doc in entries:
        data = json.dumps(doc.data(), sort_keys=True, default=str)
        sig = hashlib.sha1(f"{doc.verstr}\0{doc.rerun}\0{doc.text}\0{data}".encode(
            "utf-8", "replace")).hexdigest()[:16]
        old = known.get(key)
        if old is not None and old[1:] == [sig, PROFILE_VERSION]:
            continue
        if old is not None:
            conn.execute("DELETE FROM similar_fts WHERE rowid = ?", (old[0],))
            conn.execute("DELETE FROM similar_doc WHERE id = ?", (old[0],))
        cur = conn.execute(
            "INSERT INTO similar_doc (app, key, verstr, rerun, cmd, version, sig, data)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (app, key, doc.verstr, doc.rerun, _cmd(commands.get(key)), PROFILE_VERSION, sig,
             data))
        conn.execute(
            f"INSERT INTO similar_fts (rowid, app, verstr, {', '.join(COLUMNS)})"
            f" VALUES (?, ?, ?, {marks(COLUMNS)})",
            (cur.lastrowid, app, doc.verstr, *doc.fts_values()))


def forget_except(conn, app, keep):
    """Drop *app*'s documents whose keys are not in *keep*."""
    forget(conn, app, [key for (key,) in conn.execute(
        "SELECT key FROM similar_doc WHERE app = ?", (app,)) if key not in keep])


def forget(conn, app, keys):
    """Drop *keys*' documents."""
    for chunk in chunks(keys):
        ids = [i for (i,) in conn.execute(
            f"SELECT id FROM similar_doc WHERE app = ? AND key IN ({marks(chunk)})",
            (app, *chunk))]
        conn.executemany("DELETE FROM similar_fts WHERE rowid = ?", [(i,) for i in ids])
        conn.executemany("DELETE FROM similar_doc WHERE id = ?", [(i,) for i in ids])


def doc_count(conn, app):
    return conn.execute("SELECT COUNT(*) FROM similar_doc WHERE app = ?", (app,)).fetchone()[0]


def stale_count(conn, app):
    """How many of *app*'s documents another profile version filed."""
    return conn.execute(
        "SELECT COUNT(*) FROM similar_doc WHERE app = ? AND version IS NOT ?",
        (app, PROFILE_VERSION)).fetchone()[0]


def document_frequencies(conn, terms):
    """``{(column, term): documents holding it}`` of *terms* ``{column: [term]}``
    (stemmed text terms; words for the structured columns); absent terms are
    left out. Over the whole file: a file shared by apps counts them all."""
    out = {}
    for column, wanted in terms.items():
        for chunk in chunks(sorted(set(wanted))):
            out.update(((column, term), doc) for term, doc in conn.execute(
                f"SELECT term, doc FROM similar_vocab WHERE col = ? AND term IN ({marks(chunk)})",
                (column, *chunk)))
    return out


def stored_docs(conn, app, verstrs):
    """``{verstr: Doc}`` as filed, with their text."""
    out = {}
    for chunk in chunks(verstrs):
        for verstr, rerun, data, text in conn.execute(
                "SELECT d.verstr, d.rerun, d.data, f.text FROM similar_doc d"
                " JOIN similar_fts f ON f.rowid = d.id"
                f" WHERE d.app = ? AND d.verstr IN ({marks(chunk)})", (app, *chunk)):
            out[verstr] = Doc.from_data(verstr, rerun, json.loads(data), text)
    return out


def reruns_of(conn, app, verstrs):
    """``{verstr: rerun key}`` of *verstrs*' documents."""
    out = {}
    for chunk in chunks(verstrs):
        out.update(conn.execute(
            f"SELECT verstr, rerun FROM similar_doc WHERE app = ? AND verstr IN ({marks(chunk)})",
            (app, *chunk)))
    return out

