#!/usr/bin/env python3
"""``LISTEN`` on Postgres channels from a daemon thread (plan 11 §4.3).

:class:`PgListener` calls ``handlers[channel](payload)`` per notification and
reconnects after a lost connection (notifications sent meanwhile are lost;
the refresh poll covers them).
"""
import logging
import threading

_LOGGER = logging.getLogger(__name__)
_WAIT_SEC = 0.5
_RETRY_SEC = 1.0


class PgListener:
    def __init__(self, dsn, handlers):
        self._dsn = dsn
        self._handlers = dict(handlers)
        self._stopped = threading.Event()
        self.listening = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="vmn-ui-listen")
        self._thread.start()

    def stop(self):
        self._stopped.set()
        self._thread.join()

    def _run(self):
        while not self._stopped.is_set():
            try:
                self._listen()
            except Exception:
                _LOGGER.debug("LISTEN connection lost", exc_info=True)
            self.listening = False
            self._stopped.wait(_RETRY_SEC)

    def _listen(self):
        import psycopg

        with psycopg.connect(self._dsn, autocommit=True) as conn:
            for channel in self._handlers:
                conn.execute(f'LISTEN "{channel}"')
            self.listening = True
            while not self._stopped.is_set():
                for note in conn.notifies(timeout=_WAIT_SEC):
                    self._dispatch(note)

    def _dispatch(self, note):
        try:
            self._handlers[note.channel](note.payload)
        except Exception:
            _LOGGER.warning("Handling NOTIFY %s failed", note.channel, exc_info=True)
