#!/usr/bin/env python3
"""Keeps the experiment indexes the dashboard is looking at fresh, off the
request path.

A request asks :meth:`Refresher.snapshot` for an index's current snapshot:
that marks the index watched and makes sure a daemon thread is refreshing it
every ``interval_sec``. The thread exits once nobody asked for ``idle_sec``,
so an app no one looks at costs nothing; the next request starts it again.
Only the very first request of an index waits (for its initial load, which
the persisted SQLite store makes fast). A refresh that fails is logged and
the last snapshot keeps being served.

A store workspace passes its :class:`~vmn_exp.ui.journal_follow.WorkspaceJournal`
along: one thread per journal ticks it every ``interval_sec``, hinting the
watched indexes, which then list only hinted and live records; their full
(reconcile) listing runs every ``full_sweep_sec`` (``reconcile_sec``).

A watched index does its filesystem work in an I/O helper process
(``use_io_process``): each stat/open on this process's threads would wait for
the GIL behind busy request threads, which starved refreshes under load.
:meth:`Refresher.stop` stops the helpers.
"""
import logging
import threading
import time

from vmn_exp.ui.gil_hint import GilHint

REFRESH_INTERVAL_SEC = 1.0
IDLE_SEC = 60.0
# Background refreshes list hinted (or new, by name) and live records, and
# everything this often: the reconcile listing (plan 11 §5.2).
RECONCILE_SEC = 3600

_LOGGER = logging.getLogger(__name__)


class InlineRefresher:
    """:class:`Refresher`'s interface, refreshing on the request path instead:
    a snapshot sees every write made before it (what ``create_app`` embeds
    without ``background_refresh``)."""

    # False: a snapshot costs a refresh, and its run states are left to be
    # read from storage.
    background = False
    # None leaves the index's sweep interval alone: every refresh lists fully.
    full_sweep_sec = None

    def snapshot(self, index, journal=None):
        return index.refresh_if_stale(0)


class _Watch:
    def __init__(self):
        self.touched_at = time.monotonic()
        self.thread = None
        self.failing = False
        self.wake = threading.Event()


class Refresher:
    # True: a snapshot is served at once, at most ~interval_sec behind.
    background = True
    full_sweep_sec = RECONCILE_SEC

    def __init__(self, interval_sec=REFRESH_INTERVAL_SEC, idle_sec=IDLE_SEC):
        self.interval_sec = interval_sec
        self.idle_sec = idle_sec
        self._watches = {}  # index -> _Watch
        self._journals = {}  # WorkspaceJournal -> its thread
        self._journal_of = {}  # index -> its WorkspaceJournal
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self.gil_hint = GilHint()

    def snapshot(self, index, journal=None):
        """*index*'s current snapshot, keeping *index* refreshed from now on
        (hinted by *journal*, when given)."""
        if journal is not None:
            self._follow(journal, index)
        self._watch(index)
        return index.snapshot()

    def watching(self, index):
        watch = self._watches.get(index)
        return bool(watch and watch.thread and watch.thread.is_alive())

    def wake_scope(self, payload):
        """Refresh at once the watched indexes of ``vmn_gen``'s
        ``<workspace>:<app>`` *payload*, instead of at their next tick."""
        app = payload.split(":", 1)[-1]
        with self._lock:
            watches = [w for i, w in self._watches.items() if i.app_name == app]
        for watch in watches:
            watch.wake.set()

    def stop(self):
        """End every refresh thread and I/O helper (for tests and shutdown)."""
        self._stopped.set()
        with self._lock:
            for watch in self._watches.values():
                watch.wake.set()
            threads = [w.thread for w in self._watches.values() if w.thread]
            threads += list(self._journals.values())
            indexes = list(self._watches)
        for thread in threads:
            thread.join()
        for index in indexes:
            close = getattr(index, "close", None)
            if close:
                close()

    def _follow(self, journal, index):
        journal.watch(index)
        with self._lock:
            self._journal_of[index] = journal
            if journal not in self._journals and not self._stopped.is_set():
                thread = threading.Thread(
                    target=self._read_journal, args=(journal,), daemon=True,
                    name="vmn-ui-journal",
                )
                self._journals[journal] = thread
                thread.start()

    def _read_journal(self, journal):
        failing = False
        while not self._stopped.is_set():
            try:
                if journal.watched:
                    journal.tick()
            except Exception:
                log = _LOGGER.debug if failing else _LOGGER.warning
                log("Reading the change journal failed", exc_info=True)
                failing = True
            else:
                failing = False
            if self._stopped.wait(self.interval_sec):
                return

    def _watch(self, index):
        if index not in self._watches:
            use_io_process = getattr(index, "use_io_process", None)
            if use_io_process:
                use_io_process()
        with self._lock:
            watch = self._watches.setdefault(index, _Watch())
            watch.touched_at = time.monotonic()
            if watch.thread is None and not self._stopped.is_set():
                watch.thread = threading.Thread(
                    target=self._run, args=(index, watch), daemon=True,
                    name="vmn-ui-refresh",
                )
                watch.thread.start()

    def _run(self, index, watch):
        # Refresh at once: a restart after idling catches up before it waits.
        while not self._idle(index, watch):
            self._refresh(index, watch)
            watch.wake.wait(self.interval_sec)
            watch.wake.clear()
            if self._stopped.is_set():
                return

    def _idle(self, index, watch):
        with self._lock:
            if time.monotonic() - watch.touched_at < self.idle_sec:
                return False
            watch.thread = None
            journal = self._journal_of.pop(index, None)
        if journal is not None:
            journal.unwatch(index)
        return True

    def _refresh(self, index, watch):
        try:
            index.refresh()
        except Exception:
            # Once per failure streak: a broken store would log every second.
            log = _LOGGER.debug if watch.failing else _LOGGER.warning
            log("Background index refresh failed; serving the last snapshot", exc_info=True)
            watch.failing = True
        else:
            watch.failing = False
            self.gil_hint.note(len(getattr(index.snapshot(), "rows", ())))
