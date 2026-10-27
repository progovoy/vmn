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

Each refreshed snapshot is handed to ``on_refresh`` (the server warms its
board and search index with it, plan 23 S8b) on the ``vmn-ui-warm`` worker,
never the refresh thread: a slow warm must not hold back the next snapshot,
and a busy warmer skips to each index's newest snapshot
(:class:`~vmn_exp.ui.latest_worker.LatestWorker`). Each listener of
:meth:`add_listener` is called with ``(index, snapshot)`` after every
refresh, inline ones too (the server files similar-runs documents and writes
its Postgres search rows with them); a :class:`NotingRefresher` tells a
listener which app an index serves.

The refresher heals itself: an error in any step of a background refresh
(the refresh, the snapshot, each listener, the warming) is logged as a
:class:`~vmn_exp.ui.failure_streak.FailureStreak` and never ends the loop; a
refresh or journal thread that ended anyway (``SystemExit`` & co, logged) is
restarted by the next request. :meth:`Refresher.health` reports each watched
index's state for the status route, and a refresh running past
``SLOW_REFRESH_SEC`` is warned about once.

A watched index does its filesystem work in an I/O helper process
(``use_io_process``): each stat/open on this process's threads would wait for
the GIL behind busy request threads, which starved refreshes under load.
:meth:`Refresher.stop` stops the helpers.
"""
import logging
import threading
import time

from vmn_exp.core.activity import activity
from vmn_exp.core.traced_lock import TracedLock
from vmn_exp.ui.failure_streak import FailureStreak
from vmn_exp.ui.gil_hint import GilHint
from vmn_exp.ui.latest_worker import LatestWorker
from vmn_exp.ui.refresh_watch import Watch

REFRESH_INTERVAL_SEC = 1.0
IDLE_SEC = 60.0
# Background refreshes list hinted (or new, by name) and live records, and
# everything this often: the reconcile listing (plan 11 §5.2).
RECONCILE_SEC = 3600
# A refresh running this long is warned about once (and reported by health()).
SLOW_REFRESH_SEC = 600

_LOGGER = logging.getLogger(__name__)


class _Listeners:
    def add_listener(self, listener):
        """Call ``listener(index, snapshot)`` after every refresh."""
        self._listeners.append(listener)

    def _notify(self, index, snapshot):
        for listener in self._listeners:
            listener(index, snapshot)


class NotingRefresher:
    """*refresher*, calling ``on_snapshot(index)`` with each index it is asked
    about (what app it serves, for the refresh listeners)."""

    def __init__(self, refresher, on_snapshot):
        self._refresher, self._on_snapshot = refresher, on_snapshot

    def __getattr__(self, name):
        return getattr(self._refresher, name)

    def snapshot(self, index, journal=None):
        self._on_snapshot(index)
        return self._refresher.snapshot(index, journal)


class InlineRefresher(_Listeners):
    """:class:`Refresher`'s interface, refreshing on the request path instead:
    a snapshot sees every write made before it (what ``create_app`` embeds
    without ``background_refresh``)."""

    # False: a snapshot costs a refresh, and its run states are left to be
    # read from storage.
    background = False
    # None leaves the sweep interval to snapshot(), whatever reconcile_sec says.
    full_sweep_sec = None

    def __init__(self):
        self._listeners = []

    def snapshot(self, index, journal=None):
        index.reconcile()  # a full listing: an in-place write shows at once
        snapshot = index.refresh().snapshot()
        self._notify(index, snapshot)
        return snapshot

    def health(self, index):
        """None: nothing refreshes in the background."""
        return None


class Refresher(_Listeners):
    # True: a snapshot is served at once, at most ~interval_sec behind.
    background = True
    full_sweep_sec = RECONCILE_SEC

    def __init__(self, interval_sec=REFRESH_INTERVAL_SEC, idle_sec=IDLE_SEC, on_refresh=None,
                 clock=time.monotonic):
        self.interval_sec = interval_sec
        self.idle_sec = idle_sec
        self.on_refresh = on_refresh  # called with each refreshed snapshot
        self._clock = clock
        self._listeners = []
        self._watches = {}  # index -> Watch
        self._journals = {}  # WorkspaceJournal -> its thread
        self._journal_of = {}  # index -> its WorkspaceJournal
        self._step_streaks = {}  # (index, post-refresh step) -> FailureStreak
        self._lock = TracedLock("refresher")
        self._stopped = threading.Event()
        self._warmer = LatestWorker(self._warm, name="vmn-ui-warm")
        self.gil_hint = GilHint()

    def snapshot(self, index, journal=None):
        """*index*'s current snapshot, keeping *index* refreshed from now on
        (hinted by *journal*, when given)."""
        if journal is not None:
            self._follow(journal, index)
        self._watch(index)
        return index.snapshot()

    def watched(self):
        """``[(index, watch)]`` of the indexes refreshed now (diagnostics)."""
        with self._lock:
            return list(self._watches.items())

    def watching(self, index):
        watch = self._watches.get(index)
        return bool(watch and watch.alive())

    def health(self, index):
        """*index*'s refresh health, read without I/O (None when unwatched):
        ``{alive, failing, failures, since_refresh_sec, refreshing_sec, last_error}``."""
        watch = self._watches.get(index)
        return None if watch is None else watch.health(self._clock())

    def wake_scope(self, payload):
        """Refresh at once the watched indexes of ``vmn_gen``'s
        ``<workspace>:<app>`` *payload*, instead of at their next tick."""
        with self._lock:
            watches = [w for i, w in self._watches.items()
                       if getattr(i, "wake_key", None) == payload]
        for watch in watches:
            watch.wake.set()

    def wake_all(self):
        """Refresh every watched index at once (missed ``vmn_gen`` notifies)."""
        with self._lock:
            watches = list(self._watches.values())
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
        self._warmer.stop()
        for index in indexes:
            close = getattr(index, "close", None)
            if close:
                close()

    def _start(self, target, args, name):
        thread = threading.Thread(target=target, args=args, daemon=True, name=name)
        thread.start()
        return thread

    def _follow(self, journal, index):
        journal.watch(index)
        with self._lock:
            self._journal_of[index] = journal
            thread = self._journals.get(journal)
            if (thread is None or not thread.is_alive()) and not self._stopped.is_set():
                if thread is not None:
                    _LOGGER.error("The change journal reader of %s had stopped; restarted it",
                                  getattr(journal, "scope", None))
                self._journals[journal] = self._start(self._read_journal, (journal,),
                                                      "vmn-ui-journal")

    def _read_journal(self, journal):
        scope = getattr(journal, "scope", None)
        streak = FailureStreak("Reading the change journal", _LOGGER, self._clock, subject=scope)
        try:
            while not self._stopped.is_set():
                try:
                    if journal.watched:
                        with activity("journal tick", key=scope):
                            journal.tick()
                except Exception as exc:
                    streak.failed(exc)
                else:
                    streak.succeeded()
                if self._stopped.wait(self.interval_sec):
                    return
        except BaseException:  # SystemExit & co: end visibly; the next request restarts it
            _LOGGER.error("The change journal reader of %s stopped", scope, exc_info=True)

    def _watch(self, index):
        if index not in self._watches:
            use_io_process = getattr(index, "use_io_process", None)
            if use_io_process:
                use_io_process()
        with self._lock:
            watch = self._watches.get(index)
            if watch is None:
                watch = self._watches[index] = Watch(getattr(index, "app_name", None),
                                                     self._clock, _LOGGER)
            watch.touched_at = self._clock()
            self._warn_if_slow(watch)
            if not watch.alive() and not self._stopped.is_set():
                if watch.thread is not None:
                    _LOGGER.error("The index refresher of %s had stopped; restarted it", watch.app)
                watch.thread = self._start(self._run, (index, watch), "vmn-ui-refresh")

    def _warn_if_slow(self, watch):
        started = watch.refresh_started
        if started is None or watch.slow_warned:
            return
        running_sec = self._clock() - started
        if running_sec >= SLOW_REFRESH_SEC:
            watch.slow_warned = True
            _LOGGER.warning("Index refresh of %s running for %.0f min", watch.app, running_sec / 60)

    def _run(self, index, watch):
        try:
            # Refresh at once: a restart after idling catches up before it waits.
            while not self._idle(index, watch):
                self._refresh(index, watch)
                watch.wake.wait(self.interval_sec)
                watch.wake.clear()
                if self._stopped.is_set():
                    return
        except BaseException:  # SystemExit & co: end visibly; the next request restarts it
            _LOGGER.error("The index refresher of %s stopped", watch.app, exc_info=True)

    def _idle(self, index, watch):
        with self._lock:
            if self._clock() - watch.touched_at < self.idle_sec:
                return False
            watch.thread = None
            journal = self._journal_of.pop(index, None)
        if journal is not None:
            journal.unwatch(index)
        return True

    def _refresh(self, index, watch):
        started = self._clock()
        watch.refresh_started, watch.slow_warned = started, False
        try:
            with activity("index refresh", key=getattr(index, "app_name", None)):
                index.refresh()
            snapshot = index.snapshot()
        except Exception as exc:  # serve the last snapshot meanwhile
            watch.streak.failed(exc)
            return
        finally:
            watch.refresh_started = None
        if watch.failing:
            watch.streak.succeeded()
        watch.refreshed_at, watch.refresh_sec = started, self._clock() - started
        self._after_refresh(index, snapshot)

    def _after_refresh(self, index, snapshot):
        """Each step after a refresh, none keeping the others from running."""
        self._step(index, "The GIL hint", self.gil_hint.note, len(getattr(snapshot, "rows", ())))
        for listener in list(self._listeners):
            self._step(index, f"The refresh listener {_name(listener)}", listener, index, snapshot)
        if self.on_refresh is not None:
            self._warmer.submit(index, (index, snapshot))

    def _warm(self, item):
        index, snapshot = item
        self._step(index, "Warming", self.on_refresh, snapshot)

    def _step(self, index, what, fn, *args):
        key = (index, fn)
        try:
            fn(*args)
        except Exception as exc:
            streak = self._step_streaks.get(key)
            if streak is None:
                streak = self._step_streaks.setdefault(key, FailureStreak(
                    f"{what} after an index refresh", _LOGGER, self._clock,
                    subject=getattr(index, "app_name", None)))
            streak.failed(exc)
        else:
            streak = self._step_streaks.get(key)
            if streak is not None:
                streak.succeeded()


def _name(listener):
    return getattr(listener, "__qualname__", None) or repr(listener)
