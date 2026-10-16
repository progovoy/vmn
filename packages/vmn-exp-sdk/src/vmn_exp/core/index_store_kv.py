#!/usr/bin/env python3
"""The key-value table of :class:`vmn_exp.core.index_store.SqliteStore`
(listing baselines, journal cursors): payloads under a scope, each with the
fingerprint it is valid for."""
import json
import sqlite3

from vmn_exp.core.sqlite_conn import in_chunks, write_tx


class KeyValues:
    """Mixed into the store: uses its ``_read``, ``_conn`` and ``_db``."""

    def kv_get(self, scope, fingerprint):
        """The payload under *scope* when stored with *fingerprint*, else None."""
        return self._read(lambda: self._kv_payload(scope, fingerprint), None)

    def _kv_payload(self, scope, fingerprint):
        row = self._conn.execute(
            "SELECT fingerprint, payload FROM exp_index_kv WHERE scope = ?", (scope,)
        ).fetchone()
        return json.loads(row[1]) if row and row[0] == fingerprint else None

    def kv_get_many(self, scopes, fingerprint):
        """``{scope: payload}`` of those of *scopes* stored with *fingerprint*."""
        return self._read(lambda: self._kv_payloads(scopes, fingerprint), {})

    def _kv_payloads(self, scopes, fingerprint):
        found = {}
        for chunk, marks in in_chunks(scopes):
            found.update(
                (scope, json.loads(payload)) for scope, fp, payload in self._conn.execute(
                    "SELECT scope, fingerprint, payload FROM exp_index_kv"
                    f" WHERE scope IN ({marks})", chunk,
                ) if fp == fingerprint
            )
        return found

    def kv_put(self, scope, fingerprint, payload):
        """Store *payload* under *scope* — best effort."""
        self.kv_put_many([(scope, fingerprint, payload)])

    def kv_put_many(self, puts):
        """Store each ``(scope, fingerprint, payload)`` of *puts* at once."""
        conn = self._db.get()
        if conn is None or not puts:
            return
        try:
            with write_tx(conn):
                conn.executemany(
                    "INSERT OR REPLACE INTO exp_index_kv (scope, fingerprint, payload)"
                    " VALUES (?, ?, ?)",
                    [(scope, fp, json.dumps(payload)) for scope, fp, payload in puts],
                )
        except sqlite3.Error as exc:
            self._db.on_error(exc)  # corrupt: recovers; else debug
