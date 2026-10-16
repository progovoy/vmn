#!/usr/bin/env python3
"""The control plane's housekeeping (plan 25 F5): expired sessions and login
states are deleted, and audit entries older than ``audit.retention_days``
(server.yml, default 365).

:class:`ControlPlaneSweeper` sweeps once when the server starts and then
every ``SWEEP_INTERVAL_SEC`` on a daemon thread; a login sweeps expired
credentials too (:class:`~vmn_exp.ui.auth.sessions.SessionService`). Every
statement is an indexed range delete, so a sweep with nothing to do is cheap.
A failed sweep is logged and retried on the next tick.
"""
import logging
import threading
import time

from vmn_exp.ui.audit import audit_key
from vmn_exp.ui.config import DEFAULT_AUDIT_RETENTION_DAYS

SWEEP_INTERVAL_SEC = 3600
_DAY_SEC = 86400

_LOGGER = logging.getLogger(__name__)


class ControlPlaneSweeper:
    def __init__(self, store, retention_days=DEFAULT_AUDIT_RETENTION_DAYS, clock=time.time,
                 interval_sec=SWEEP_INTERVAL_SEC):
        self.store = store
        self.retention_days = retention_days
        self.clock = clock
        self.interval_sec = interval_sec
        self._stop = threading.Event()
        self._swept = threading.Event()
        self._thread = None

    def sweep(self):
        now = self.clock()
        self.store.sweep_expired(now)
        self.store.delete_keys_below("audit", audit_key(now - self.retention_days * _DAY_SEC))

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="vmn-ui-control-plane-sweep")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def wait_first(self, timeout=10):
        """Block until the first sweep since :meth:`start` ran (tests)."""
        return self._swept.wait(timeout)

    def _run(self):
        while True:
            try:
                self.sweep()
            except Exception:
                _LOGGER.warning("Control-plane sweep failed", exc_info=True)
            self._swept.set()
            if self._stop.wait(self.interval_sec):
                return


def install(app, store, retention_days):
    """``app.state.sweeper``, sweeping from the server's start to its shutdown."""
    sweeper = app.state.sweeper = ControlPlaneSweeper(store, retention_days)
    app.router.on_startup.append(sweeper.start)
    app.router.on_shutdown.append(sweeper.stop)
    return sweeper
