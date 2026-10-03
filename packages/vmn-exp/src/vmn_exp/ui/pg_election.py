#!/usr/bin/env python3
"""Leader election across replicas on one Postgres (plan 11 §4.3).

:meth:`AdvisoryElection.lead` holds a session-level
``pg_try_advisory_lock`` per name on a dedicated connection: whoever holds it
leads. When that session dies (a crashed replica, a killed backend) the locks
free and another replica takes them on its next try. A replica that finds its
own session lost sits out one try, so the handover goes to a replica that
was waiting rather than straight back to it.
"""
import logging
import threading

_LOGGER = logging.getLogger(__name__)
# Two-int advisory keys (class, hashtext(name)) never overlap the single
# bigint key the migrations lock uses.
_LOCK_CLASS = 0x766D6E


class AdvisoryElection:
    def __init__(self, dsn):
        self._dsn = dsn
        self._conn = None
        self._held = set()
        self._lock = threading.Lock()
        self.backend_pid = None

    def lead(self, name):
        """True while this replica leads *name* (taking it when it is free)."""
        with self._lock:
            if self._conn is not None and not self._alive():
                self._drop()
                return False
            try:
                return self._try(name)
            except Exception:
                _LOGGER.debug("Leader election for %s failed", name, exc_info=True)
                self._drop()
                return False

    def notify(self, channel, payload):
        """``NOTIFY`` *channel* on the election's connection (best effort)."""
        with self._lock:
            try:
                self._connection().execute("SELECT pg_notify(%s, %s)", (channel, payload))
            except Exception:
                _LOGGER.debug("NOTIFY %s failed", channel, exc_info=True)
                self._drop()

    def close(self):
        with self._lock:
            self._drop()

    def _try(self, name):
        if name in self._held:
            return True
        (got,) = self._connection().execute(
            "SELECT pg_try_advisory_lock(%s, hashtext(%s))", (_LOCK_CLASS, name)
        ).fetchone()
        if got:
            self._held.add(name)
        return got

    def _alive(self):
        try:
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def _connection(self):
        if self._conn is None:
            import psycopg

            self._conn = psycopg.connect(self._dsn, autocommit=True)
            self.backend_pid = self._conn.info.backend_pid
        return self._conn

    def _drop(self):
        self._held.clear()
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
