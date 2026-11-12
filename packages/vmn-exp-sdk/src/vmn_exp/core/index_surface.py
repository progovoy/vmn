#!/usr/bin/env python3
"""What :class:`~vmn_exp.core.index.ExperimentIndex` shows its readers: its
properties, the journal pass-throughs to its sweep, freshness, and the
snapshots and row copies it serves (a mixin; all state stays on the index).

Readers get an immutable :class:`IndexSnapshot` per ``generation`` (bumped by
anything visible, run states included) that never takes the index lock or
touches storage. Its rows are ``experiment_row``'s under no metrics schema and
without ``metric_summary`` or ``outputs`` (the snapshot keeps them per
verstr; the row copies handed out carry them) — nor the run's
``features``/``intent``/hypothesis, which only the snapshot keeps; a caller's
schema is a view of it (:meth:`IndexSnapshot.summarized`), never index state.
Status is derived from its run states on every read, since it depends on the
clock."""
import logging
import threading

from vmn_exp.core import index_freshness
from vmn_exp.core.index_bulk import loading_snapshot
from vmn_exp.core.index_rows import row_copies as _row_copies

# The facade's logger: tests filter captured records by this name.
_LOGGER = logging.getLogger("vmn_exp.core.index")
# How long a request on an index that published nothing yet waits for its
# first snapshot before it gets an empty one saying it is loading.
FIRST_SNAPSHOT_WAIT_SEC = 0.5


class IndexSurface:
    @property
    def path(self):
        """The file the index persists in, or None."""
        return getattr(self._store, "path", None)

    @property
    def full_sweep_sec(self):
        """Seconds between full listings (default 300); 0 lists fully every time."""
        return self._sweep.full_sweep_sec

    @full_sweep_sec.setter
    def full_sweep_sec(self, value):
        self._sweep.full_sweep_sec = value

    @property
    def journaled(self):
        """True: refreshes list only hinted and live records (plan 11 §5.2)."""
        return self._sweep.journaled

    @journaled.setter
    def journaled(self, value):
        self._sweep.journaled = value

    def hint(self, name):
        """The store's journal named *name*: the next refresh re-reads it (and
        loads it, if new) without listing anything else."""
        self._sweep.hint(name)

    def journal_at(self, ms):
        """The journal hinted every entry up to *ms* (its reader's cursor):
        once refreshed, the records stand at that mark (persisted with them)."""
        self._sweep.journal_at(ms)

    def resume_journal(self, oldest_ms):
        """Carry on from the persisted records when their journal mark is
        no older than *oldest_ms* (the oldest entry the journal still holds):
        no full listing, the caller replays the journal from the mark it
        returns. None: no such mark — the index needs :meth:`reconcile`."""
        mark = self._mark.load()
        if mark is None or mark < oldest_ms:
            return None
        self._sweep.resume()
        return mark

    def overflowed(self, names):
        """The journal named too many of the app's records in one tick:
        re-read *names* and list the record names (not their files) for
        anything else it missed."""
        self._sweep.overflowed(names)

    @property
    def drift(self):
        """Records the consistency check found changed with no journal entry."""
        return self._sweep.drift

    @property
    def last_reconcile_at(self):
        """Wall time the last full listing or consistency round began."""
        return self._sweep.last_reconcile_at

    @property
    def records(self):
        """A copy of ``{key: record}`` as last refreshed."""
        return dict(self._records or {})

    @property
    def record_count(self):
        return len(self._records or ())

    @property
    def published(self):
        """The current snapshot, or None before the first (never waits)."""
        return self._snapshot

    @property
    def refreshing(self):
        """True while a refresh holds the index (diagnostics; never waits)."""
        return self._lock.locked()

    def freshness(self):
        """``{as_of, refreshing, phase, progress}`` of the current snapshot
        (:mod:`~vmn_exp.core.index_freshness`), plus ``stalled_sec`` while a
        refresh runs; never waits. A journaled index's full listing behind
        serving (progress: the share of records listed) or catch-up on the
        journal (a replay, an overflow, hints queued) shows as
        ``full_listing``/``journal`` between refreshes too. ``unreadable``
        (:meth:`Unreadable.summary`: the I/O helper's, which reads the
        records) counts the records set aside, absent when none."""
        state = self._reported_freshness()
        if state["refreshing"]:
            state["stalled_sec"] = self._freshness.stalled_sec(state["phase"], state["progress"])
        unreadable = self._io_unreadable if self._io is not None else self._unreadable.summary()
        if unreadable:
            state["unreadable"] = unreadable
        checking = self._vmx.state()
        if checking:
            state["checking"] = checking
        return state

    def _reported_freshness(self):
        state = self._freshness.state(self._lock.locked())
        behind = self._sweep.listing_phase()
        if state["phase"] == index_freshness.MIGRATING:
            return state
        if behind is not None and (
                behind[0] == index_freshness.FULL_LISTING or state["phase"] == index_freshness.IDLE):
            state["phase"], state["progress"] = behind
        new = self._sweep.relisted_new()
        loading = self._loading(len(self._order or ()))
        if loading is not None and (new is None or (new and new[1] > self._chunk())):
            rows, expected = loading  # a cold index's load behind serving: the share served
            state["progress"] = round(rows / expected, 3) if expected else None
        return state

    def full_listing_due(self):
        """Whether the next refresh lists storage fully (diagnostics)."""
        return self._sweep._full_due(self._monotonic())

    def reconcile(self):
        """Make the next refresh a full listing."""
        self._sweep.request_full()

    # -- snapshots -----------------------------------------------------------

    def snapshot_now(self, wait_sec=FIRST_SNAPSHOT_WAIT_SEC):
        """The current :class:`IndexSnapshot`, never waiting for a first load
        longer than *wait_sec* (what a background-refreshed server serves):
        until one is published, an empty snapshot whose ``loading`` is ``(0,
        records expected)`` — None while not even their names are listed."""
        snap = self._snapshot
        if snap is not None or self._cache_gen is not None:
            return snap or self._first_load()
        self._revalidate_in_background()
        self._servable.wait(wait_sec)
        snap = self._snapshot or self._first_rows
        if snap is not None:
            return snap
        new = self._sweep.relisted_new()
        expected = new[0] + new[1] if new else None
        if self._placeholder is None or self._placeholder[0] != expected:
            self._placeholder = (expected, loading_snapshot(self.app_name, expected))
        return self._placeholder[1]

    def snapshot(self):
        """The current :class:`IndexSnapshot`. The first call of an index
        with persisted records answers them as soon as they are read and
        refreshes them from storage in the background; a cold index answers
        once its first load is done."""
        snap = self.published
        if snap is not None:
            return snap
        if self._cache_gen is not None:
            return self._first_load()
        self._revalidate_in_background()
        self._published.wait()
        # The background load failed: load here, meeting its error.
        return self._snapshot or self._first_load()

    def _revalidate_in_background(self):
        with self._revalidator_lock:
            if self._revalidator is not None:
                return
            self._revalidator = threading.Thread(
                target=self._revalidate, daemon=True, name="vmn-index-revalidate"
            )
            self._revalidator.start()

    def _revalidate(self):
        try:
            self.refresh()
        except Exception:
            _LOGGER.debug("Background index refresh failed", exc_info=True)

    def wait_revalidated(self, timeout=None):
        """Wait for the refresh a first :meth:`snapshot` started, if any."""
        if self._revalidator is not None:
            self._revalidator.join(timeout)

    # -- copies of the current snapshot (call refresh() first) ---------------

    def rows(self, with_create_note=False):
        """``experiment_row`` dicts in storage order — fresh copies, ``idx`` and
        ``metric_summary`` and ``outputs`` set.

        ``with_create_note`` adds ``create_note``: the first ``create`` entry's
        note, which ``vmn-exp list`` shows for a run without a metadata note.
        """
        snap = self._snapshot
        return _row_copies(snap, with_create_note) if snap is not None else []

    def run_states(self):
        """``{verstr: raw run state or None}`` for the rows' experiments."""
        snap = self._snapshot
        return dict(snap.run_states) if snap is not None else {}
