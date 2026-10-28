#!/usr/bin/env python3
"""The store upkeep ``vmn-exp ui`` does itself unless ``--read-only``: what
``vmn-exp backfill-children`` and ``vmn-exp watch --compact`` do by hand.

After an index refresh (a refresher listener, :meth:`StoreUpkeep.refreshed`)
a store workspace app's snapshot is handed to one worker thread, which runs
an :class:`AppUpkeep` pass over it at most every ``interval_sec`` per index:

* child markers (:mod:`vmn_exp.storage.child_markers`): a parent's markers
  are listed the first time a pass sees it, and again when more than
  :data:`RELIST_OVER` of its children are new (a cold load shows them 500 at
  a time); a few new children are marked directly (one PUT each; markers are
  idempotent), so a steady pass costs nothing for the runs it has checked;
* compaction (:mod:`vmn_exp.core.metric_compact`, :mod:`vmn_exp.core.log_compact`)
  of each failed or stuck run, once per server process, newest first, until
  the pass's ``budget_sec`` is spent (the next pass goes on): a dead writer's
  hundreds of 30 s segments become one indexed object, so its charts cost
  two round trips. A run whose listings already show its metrics on ``.vmx``
  files alone and one log object per stream (compacted before a restart)
  costs those two listings, never a read of its log.

Only the replica leading an index (an elected index's ``leading``) works on
it. Failures are logged, never raised, and a run whose compaction failed is
not retried before the server restarts.
"""
import logging
import threading
import time
from collections import defaultdict

from vmn_exp.core.activity import activity
from vmn_exp.core.log_compact import compact_record_logs
from vmn_exp.core.metric_compact import compact_record
from vmn_exp.core.status import FAILED, STUCK, derive_status
from vmn_exp.core.traced_lock import TracedLock

UPKEEP_INTERVAL_SEC = 60
PASS_BUDGET_SEC = 30
RELIST_OVER = 100

DEAD = (FAILED, STUCK)

_LOGGER = logging.getLogger(__name__)


class AppUpkeep:
    """One app's upkeep state across passes."""

    def __init__(self, storage, app_name, clock=time.monotonic):
        self._storage, self._app, self._clock = storage, app_name, clock
        self._listed = set()  # parents whose markers were listed
        self._marked = set()  # (parent, child) known to be marked
        self._compacted = set()  # verstrs compacted (or failed to) this process

    def run(self, snapshot, budget_sec=PASS_BUDGET_SEC):
        """One pass over *snapshot*: ``{"marked", "compacted", "failed"}``."""
        counts = {"marked": 0, "compacted": 0, "failed": 0}
        self._mark_children(snapshot.rows, counts)
        self._compact_dead(snapshot, self._clock() + budget_sec, counts)
        return counts

    def _mark_children(self, rows, counts):
        known = {row["verstr"] for row in rows}
        pending = defaultdict(list)
        for row in rows:
            parent = row.get("parent")
            if parent in known and parent != row["verstr"] \
                    and (parent, row["verstr"]) not in self._marked:
                pending[parent].append(row["verstr"])
        for parent, kids in pending.items():
            present = self._listing(parent, len(kids))
            for kid in kids:
                if kid in present or self._mark(parent, kid, counts):
                    self._marked.add((parent, kid))

    def _listing(self, parent, unchecked):
        """*parent*'s markers: listed the first time, and again when more than
        :data:`RELIST_OVER` of its children are unchecked (a page of 1000
        markers beats a PUT each); else none, and the children are PUT."""
        if parent in self._listed and unchecked <= RELIST_OVER:
            return ()
        self._listed.add(parent)
        return set(self._storage.list_children(self._app, parent))

    def _mark(self, parent, kid, counts):
        try:
            self._storage.mark_child(self._app, parent, kid)
        except Exception:
            _LOGGER.warning("Store upkeep of %s: marking %s in %s failed", self._app, kid,
                            parent, exc_info=True)
            counts["failed"] += 1
            return False
        counts["marked"] += 1
        return True

    def _compact_dead(self, snapshot, deadline, counts):
        for verstr in self._dead(snapshot):
            if self._clock() >= deadline:
                return
            self._compacted.add(verstr)
            try:
                merged = compact_record(self._storage, self._app, verstr)
                merged += compact_record_logs(self._storage, self._app, verstr)
            except Exception:
                _LOGGER.warning("Store upkeep of %s: compacting %s failed", self._app, verstr,
                                exc_info=True)
                counts["failed"] += 1
            else:
                counts["compacted"] += bool(merged)

    def _dead(self, snapshot):
        """The failed/stuck runs not compacted yet, newest first."""
        observed = snapshot.run_state_observed_at
        dead = [row for row in snapshot.rows if row["verstr"] not in self._compacted
                and derive_status(snapshot.run_states.get(row["verstr"]),
                                  observed_at=observed.get(row["verstr"])) in DEAD]
        dead.sort(key=lambda row: row.get("timestamp") or "", reverse=True)
        return [row["verstr"] for row in dead]


class StoreUpkeep:
    """Runs :class:`AppUpkeep` passes for the noted indexes on one thread."""

    def __init__(self, interval_sec=UPKEEP_INTERVAL_SEC, budget_sec=PASS_BUDGET_SEC):
        self.interval_sec, self.budget_sec = interval_sec, budget_sec
        self._apps = {}  # index -> AppUpkeep
        self._pending = {}  # index -> the newest snapshot not passed over yet
        self._last_pass = {}  # index -> monotonic time of its last pass
        self._lock = threading.Condition(TracedLock("store upkeep", reentrant=True))
        self._busy = False
        self._stopped = False
        self._thread = None

    def note(self, index, storage, app_name):
        """*index* serves *app_name* of the store *storage*."""
        with self._lock:
            if index not in self._apps:
                self._apps[index] = AppUpkeep(storage, app_name)

    def refreshed(self, index, snapshot):
        with self._lock:
            if index not in self._apps or self._stopped:
                return
            self._pending[index] = snapshot
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, daemon=True,
                                                name="vmn-ui-upkeep")
                self._thread.start()
            self._lock.notify_all()

    def wait_idle(self, timeout):
        """Whether every pending pass ran within *timeout* seconds (tests)."""
        with self._lock:
            return self._lock.wait_for(lambda: not self._pending and not self._busy, timeout)

    def stop(self):
        with self._lock:
            self._stopped = True
            self._lock.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join()

    def _work(self):
        while True:
            with self._lock:
                self._lock.wait_for(lambda: self._stopped or self._due(), self.interval_sec or None)
                if self._stopped:
                    return
                index = self._due()
                if index is None:
                    continue
                snapshot = self._pending.pop(index)
                self._last_pass[index] = time.monotonic()
                self._busy = True
            try:
                self._pass(index, snapshot)
            finally:
                with self._lock:
                    self._busy = False
                    self._lock.notify_all()

    def _due(self):
        now = time.monotonic()
        for index in self._pending:
            if now - self._last_pass.get(index, -self.interval_sec) >= self.interval_sec:
                return index
        return None

    def _pass(self, index, snapshot):
        if not getattr(index, "leading", True):
            return
        try:
            with activity("store upkeep", key=snapshot.app_name):
                counts = self._apps[index].run(snapshot, self.budget_sec)
        except Exception:
            _LOGGER.warning("Store upkeep of %s failed", snapshot.app_name, exc_info=True)
            return
        if any(counts.values()):
            _LOGGER.info(f"Store upkeep of {snapshot.app_name}: marked {counts['marked']} "
                         f"children, compacted {counts['compacted']} runs, "
                         f"failed {counts['failed']}")
