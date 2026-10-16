#!/usr/bin/env python3
"""Postgres connections of the server (plan 25 §2): one
``psycopg_pool.ConnectionPool`` per DSN per process, shared by the cache,
control plane and search.

Every connection gets a ``connect_timeout`` and TCP keepalives. Pooled
(request) connections also get a ``statement_timeout`` /
``idle_in_transaction_session_timeout``; dedicated ones (:func:`connect`, for
the migrations, the election's session locks and LISTEN) do not. Settings
already in the DSN win over these defaults (``?options=-c statement_timeout=…``).
A pool checks a connection on checkout and replaces a broken one, so a
restarted database is reconnected without a process restart. The migrations
run once per DSN per process, before its pool opens, under their advisory
lock (:mod:`vmn_exp.ui.migrations`).
"""
import contextlib
import threading

from vmn_exp.ui import migrations
from vmn_exp.ui.tenancy import bind_org

CONNECT_TIMEOUT_SEC = 5
STATEMENT_TIMEOUT = "30s"
IDLE_IN_TRANSACTION_TIMEOUT = "60s"
CHECKOUT_TIMEOUT_SEC = 10
MIN_SIZE, MAX_SIZE = 1, 10
_KEEPALIVES = {
    "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
}

_pools = {}  # dsn -> ConnectionPool
_lock = threading.Lock()


def conninfo(dsn, *, request=False):
    """*dsn* with the default keepalives and connect timeout where it sets
    none, plus the request timeouts when *request*."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(dsn)
    for key, value in dict(_KEEPALIVES, connect_timeout=CONNECT_TIMEOUT_SEC).items():
        params.setdefault(key, value)
    if request:
        defaults = (f"-c statement_timeout={STATEMENT_TIMEOUT}"
                    f" -c idle_in_transaction_session_timeout={IDLE_IN_TRANSACTION_TIMEOUT}")
        # Later -c settings win: the DSN's own options come last.
        params["options"] = f"{defaults} {params.get('options', '')}".strip()
    return make_conninfo(**params)


def connect(dsn):
    """A dedicated autocommit connection to *dsn* (no migrations)."""
    import psycopg

    return psycopg.connect(conninfo(dsn), autocommit=True)


def pool(dsn):
    """The process's pool of autocommit connections to the migrated *dsn*."""
    with _lock:
        found = _pools.get(dsn)
        if found is None:
            _migrate(dsn)
            found = _pools[dsn] = _open(dsn)
        return found


@contextlib.contextmanager
def org_tx(dsn, org):
    """A pooled connection to *dsn* in a transaction bound to *org* (no org
    bound when it is ``None``)."""
    with pool(dsn).connection() as conn, conn.transaction():
        if org is not None:
            bind_org(conn, org)
        yield conn


def close_all():
    """Close every pool (tests and shutdown)."""
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for each in pools:
        each.close()


def _migrate(dsn):
    with connect(dsn) as conn:
        # A DSN's own statement timeout never cancels a migration.
        conn.execute("SET statement_timeout = 0")
        migrations.apply_migrations(conn)


def _open(dsn):
    from psycopg_pool import ConnectionPool

    return ConnectionPool(
        conninfo(dsn, request=True), kwargs={"autocommit": True}, min_size=MIN_SIZE, max_size=MAX_SIZE,
        timeout=CHECKOUT_TIMEOUT_SEC, check=ConnectionPool.check_connection,
        name="vmn-ui-pg", open=True,
    )
