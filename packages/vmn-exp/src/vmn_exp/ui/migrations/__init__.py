#!/usr/bin/env python3
"""Numbered SQL migrations for the Postgres server state (``NNNN_name.sql``).

:func:`apply_migrations` runs the ones not yet recorded in
``vmn_schema_migrations``, in order, under a ``pg_advisory_lock`` so replicas
starting together apply each file once.
"""
import pathlib

_DIR = pathlib.Path(__file__).parent
_LOCK_ID = 0x766D6E  # "vmn"


def connect(dsn):
    """An autocommit connection to *dsn* with every migration applied."""
    import psycopg

    conn = psycopg.connect(dsn, autocommit=True)
    try:
        apply_migrations(conn)
    except Exception:
        conn.close()
        raise
    return conn


def migration_files():
    return sorted(_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def apply_migrations(conn):
    """Apply pending migrations on an autocommit *conn*; returns their names."""
    conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS vmn_schema_migrations"
            " (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {name for (name,) in conn.execute("SELECT name FROM vmn_schema_migrations")}
        applied = [path.name for path in migration_files() if path.name not in done]
        for name in applied:
            with conn.transaction():
                conn.execute((_DIR / name).read_text())
                conn.execute("INSERT INTO vmn_schema_migrations (name) VALUES (%s)", (name,))
        return applied
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
