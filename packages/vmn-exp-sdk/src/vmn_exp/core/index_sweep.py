#!/usr/bin/env python3
"""Which records an :mod:`experiment_index` refresh lists the files of.

Stat-ing every file of every record on each refresh costs seconds at a few
thousand runs. So a refresh asks the backend's ``list_record_names`` for
``{name: sig}`` — a cheap per-record signature (the local record directory's
mtime and inode, which every atomic write bumps), or None where the backend
cannot know — and lists the files of just the records that can have changed:
new ones, running ones (only a fresh heartbeat can still move on its own),
and every other status — ``created``, ``stuck``, ``succeeded``, ``failed`` —
only once its sig moved or it changed within the touch window (a
run's last metrics may land after its exit code, and appends leave the sig
alone). A ``stuck`` run is not going to un-stick itself, but a write that
resumes it still bumps its sig, which the same check catches next cycle.

Every ``full_sweep_sec`` — and always for a backend without names-only
listing, or one answering None — one full ``list_files`` catches what no sig
shows (any change to a record whose sig is None, a record removed only partly).
A plain set of names is accepted as all-None sigs.

Listings arrive as changes (:class:`~vmn_exp.core.index_listing.ListingWatch`),
so a refresh judges only the records that moved, the live ones and the
recently touched ones — never all N: at 100k records a status per record per
refresh was most of its CPU. The index reports each record it refreshed
(:meth:`Sweep.track`) so the live set stays current.

A watch that says it is ``rolling`` (the server's I/O helper) never lists
everything at once after the first listing: each refresh also re-lists the
next slice of the known records, sized so every one comes round within
``full_sweep_sec`` — at 100k records one full listing kept a refresh, and so
every new run, waiting for seconds. A slice never exceeds
:data:`SLICE_BUDGET` records, however big the store or long the last
refresh, and slices add up to at most :data:`MAX_RECHECK_PER_SEC` records a
second: a bigger store's round just takes longer (N / MAX_RECHECK_PER_SEC
seconds; at 486k S3 records an unbounded slice was 48k records, and one
refresh 97 minutes).

A ``journaled`` sweep (the ui, reading the store's change journal; plan 11
§5.2) lists the files of the records the journal named (:meth:`Sweep.hint`)
and of each live one at its own heartbeat cadence (:func:`live_relist_sec`;
for its heartbeats, which the journal leaves out), plus the same rolling slice
of every known record — the consistency check (plan 11 §4.6), so each comes
round once per ``full_sweep_sec`` (``reconcile_sec``), or per the two
bounds above when that is longer — and, at the start of each round,
the record names (for records no journal entry announced). Only the check is
budgeted: hinted, live and new records are listed at once. What the check finds
changed that no hint or live listing explains is counted in :attr:`Sweep.drift`.
Its only full listings are the first one and :meth:`Sweep.request_full`.

``full_sweep_sec`` (default 300; 0 lists fully every time) holds across
processes: the baselines persist (:mod:`~vmn_exp.core.index_baseline`), so a
new process lists names once and the files of only the records above. What no
sig shows — a settled record changed in place behind vmn's back (every vmn
write moves its sig), on another host behind its local copy, or on S3 — shows
up by the next full sweep, whichever process runs it.
"""
import threading
import time

from vmn_exp.core.index_lazy import has_meta
from vmn_exp.core.index_listing import METADATA_FILE, ListingWatch, as_sigs  # noqa: F401
from vmn_exp.core.index_sweep_state import SweepState, _settled
from vmn_exp.core.status import heartbeat_interval_sec, stale_after_sec

DEFAULT_FULL_SWEEP_SEC = 300  # 0: every refresh is a full listing
# The most records one refresh re-lists for the consistency check (and the
# most credit it keeps), whatever the store's size or the last refresh's
# length. On S3 a record's files are three delimited LISTs (the record, log/,
# metrics/), so 500 are ~1500 requests: a few seconds at S3_WORKERS in
# parallel, which the refresh, and so every new run, waits for; a local store
# lists them in milliseconds.
SLICE_BUDGET = 500
# The most records a second the consistency check re-lists, sustained: it is
# a safety net beside the journal and the signatures, so ~150 S3 LISTs a
# second is plenty (486k records every 3600 s would be 135 records, ~400
# LISTs, a second forever). Stores up to 50 * full_sweep_sec records (the
# ui: 180k) still come round every full_sweep_sec; a 486k one takes ~2.7 h.
MAX_RECHECK_PER_SEC = 50
# The shortest period a journaled sweep re-lists a live record the journal
# did not name at (and a pending claim's): the journal names every write but
# a heartbeat-only run_state.yml (see live_relist_sec).
LIVE_RELIST_SEC = 10
# How long a changed record keeps being listed (capped by full_sweep_sec).
TOUCH_WINDOW_SEC = 300
_wall = time.time


def live_relist_sec(record):
    """How often a journaled sweep lists live *record* (None: a pending
    claim) for its heartbeat: once per beat, never more often than
    LIVE_RELIST_SEC, and within half its stale window, so a beat that landed
    is seen long before the run would read ``stuck`` without it."""
    if record is None:
        return LIVE_RELIST_SEC
    run_state = record.get("run_state")
    period = max(heartbeat_interval_sec(run_state), LIVE_RELIST_SEC)
    return min(period, stale_after_sec(run_state) / 2)


class Sweep(SweepState):
    """The listing policy of one index; times are the caller's monotonic clock."""

    def __init__(self, storage, app_name, full_sweep_sec=DEFAULT_FULL_SWEEP_SEC, watch=None):
        self.full_sweep_sec = full_sweep_sec
        self.watch = watch or ListingWatch(storage, app_name)
        self._last_full = None
        self._touched = {}  # key -> when a refresh last saw it change
        self._sigs = {}  # key -> its sig at the last listing
        self._sigs_known = True  # False once the backend answered only None sigs
        self._live = None  # keys that may change on their own; None: not judged yet
        self._live_at = {}  # key -> when a journaled listing last listed it as live
        self._pending = set()  # names listed without metadata yet (claims)
        self._ring, self._cursor, self._credit, self._rolled_at = [], 0, 0.0, None
        self.journaled = False
        self._hinted = set()  # keys the journal named since the last listing
        self._hint_lock = threading.Lock()
        self._explained = set()  # keys listed by a hint or as live since their last check
        self._wrapped = False  # the rolling slice started a new round
        self.drift = 0  # records the consistency check found changed unannounced
        self.last_reconcile_at = None  # wall time a full listing or round last began
        self._restored = False  # baselines restored: check the records against them

    def reset(self):
        """Forget every baseline: the next listing is full and compares all."""
        self.watch.reset()
        self._last_full, self._sigs, self._live, self._pending = None, {}, None, set()
        self._live_at = {}
        self._restored = False
        self._ring, self._cursor, self._credit, self._rolled_at = [], 0, 0.0, None

    def touch(self, key, now):
        self._touched[key] = now

    def track(self, key, record=None):
        """*key*'s record was (re)loaded as *record*: judge it again at the
        next listing — unless *record* already says it is no live run."""
        if self._live is None:
            return
        if record is not None and (not has_meta(record) or _settled(record)):
            self._live.discard(key)
        else:
            self._live.add(key)

    def hint(self, key):
        """The journal says *key* changed: list its files at the next listing."""
        with self._hint_lock:
            self._hinted.add(key)

    def request_full(self):
        """Make the next listing a full (reconcile) one."""
        self._last_full = None

    def _take_hints(self):
        with self._hint_lock:
            hinted, self._hinted = self._hinted, set()
        return hinted

    def forget(self, key):
        self._touched.pop(key, None)
        self._sigs.pop(key, None)
        self._pending.discard(key)
        self._live_at.pop(key, None)
        if self._live is not None:
            self._live.discard(key)

    def listing(self, records, now):
        """``(files of the records to refresh, keys of records gone)``."""
        if self.journaled:
            return self._journaled_listing(records, now)
        full_due = self._full_due(now)
        changes = self._name_changes(journal=not full_due)
        if changes is None or full_due:
            if changes is not None:
                self._apply_sigs(*changes)
            return self._full_listing(records, now)
        changed, gone_names = changes
        if self._restored:
            changed, gone_names = self._against_records(records, changed, gone_names)
        keys = self._to_list(records, changed, gone_names, now)
        listing = self.watch.files(keys)
        gone = {key for key in keys if METADATA_FILE not in listing.get(key, {})}
        if self.watch.rolling and self.full_sweep_sec:
            rolled, rolled_gone = self.watch.slice_changes(self._next_slice(now, self._sigs))
            listing = {**rolled, **listing}
            gone |= rolled_gone
        self._pending = {key for key in gone if key in self._sigs and key not in records}
        return listing, [key for key in gone | gone_names if key in records]

    def _journaled_listing(self, records, now):
        hinted = self._take_hints()
        if self._full_due(now):
            return self._full_listing(records, now)
        candidates = hinted | self._pending | self._live
        keys = [key for key in candidates if key in hinted or self._live_due(records, key, now)]
        self._explained.update(keys)
        listing = self.watch.files(keys)
        gone = {key for key in keys if METADATA_FILE not in listing.get(key, {})}
        checked, checked_gone = self._consistency_check(records, now)
        self._pending = {key for key in gone if key in hinted | self._pending
                         and key not in records}
        self._pending |= {k for k, files in checked.items() if METADATA_FILE not in files}
        return {**checked, **listing}, [key for key in gone | checked_gone if key in records]

    def _consistency_check(self, records, now):
        """``(files of the slice's changed records, keys gone)``, counting drift."""
        due = self._next_slice(now, records)
        changed, gone = self.watch.slice_changes(due) if due else ({}, set())
        if self._wrapped:
            unseen = self._unseen_names(records)
            new, _ = self.watch.slice_changes(unseen) if unseen else ({}, set())
            changed = {**new, **changed}
        unexplained = [
            k for k, files in changed.items()
            if k not in self._explained and METADATA_FILE in files
        ]
        self.drift += len(unexplained) + sum(key in records for key in gone)
        self._explained.difference_update(due)
        return changed, gone

    def _unseen_names(self, records):
        """Names the store lists that the index does not know (nor waits for)."""
        changes = self.watch.name_changes()
        if changes is None:
            return []
        return [k for k in changes[0] if k not in records and k not in self._pending]

    def _live_due(self, records, key, now):
        """Whether live (or pending) *key* is due its :func:`live_relist_sec`
        listing, which keeps its heartbeat fresh; its other writes are hinted.
        Its clock starts when first seen live: it was just listed or loaded."""
        if not self._judge_live(records, key):
            self._live_at.pop(key, None)
            return False
        if now - self._live_at.setdefault(key, now) < live_relist_sec(records.get(key)):
            return False
        self._live_at[key] = now
        return True

    def _judge_live(self, records, key):
        """Whether *key* — pending or live — is still worth listing."""
        record = records.get(key)
        if record is None:
            return True  # a claim still waiting for its metadata
        if not has_meta(record) or _settled(record):
            self._live.discard(key)
            return False
        return True

    def _name_changes(self, journal=False):
        # Sigs are kept even while every refresh is full, so switching the
        # fast tier on later does not re-list every record once — unless the
        # backend has no sigs to give (S3), where asking is a wasted listing.
        if not self.full_sweep_sec and not self._sigs_known:
            return None
        changes = self.watch.name_changes(_wall(), journal)
        if changes is None:
            return None
        changed, gone = changes
        if changed:
            self._sigs_known = any(sig is not None for sig in changed.values())
        return changed, gone

    def _apply_sigs(self, changed, gone):
        self._sigs.update(changed)
        for key in gone:
            self._sigs.pop(key, None)

    def _to_list(self, records, changed, gone, now):
        self._touched = {
            k: t for k, t in self._touched.items() if now - t < self._touch_window()
        }
        # A journal names every later write, appends included: no touch window.
        touched = () if getattr(self.watch, "from_journal", False) else self._touched
        candidates = (set(changed) | self._pending | self._live | set(touched)) - gone
        keys = []
        for key in candidates:
            if self._judge(records, key, changed.get(key, self._sigs.get(key)), now):
                keys.append(key)
        self._apply_sigs(changed, gone)
        return keys

    def _judge(self, records, key, sig, now):
        """:meth:`_may_change`, keeping the live set current on the way."""
        record = records.get(key)
        if record is None or not has_meta(record):
            self._live.discard(key)
            return record is None
        settled = _settled(record)
        (self._live.discard if settled else self._live.add)(key)
        return self._changed_since(key, sig, now, settled)

    def _next_slice(self, now, population):
        """The keys of *population* due for their periodic re-listing. A
        refresh lists at most a tenth of them, and never more than
        SLICE_BUDGET, however long the last one took (a cold load can outlast
        full_sweep_sec); credit accrues at most MAX_RECHECK_PER_SEC a second:
        a big store's round just takes longer."""
        elapsed = now - (self._rolled_at if self._rolled_at is not None else now)
        elapsed = min(elapsed, self.full_sweep_sec / 10)
        self._rolled_at = now
        size = max(len(population), 1)  # an empty one still starts rounds
        rate = min(size / self.full_sweep_sec, MAX_RECHECK_PER_SEC)
        accrued = self._credit + rate * elapsed
        self._credit = min(accrued, size, SLICE_BUDGET)
        self._wrapped = False
        due = []
        while len(due) < int(self._credit):
            if self._cursor >= len(self._ring):
                self._ring, self._cursor = sorted(population), 0
                self._wrapped, self.last_reconcile_at = True, _wall()
                if not self._ring:
                    self._credit = 0
                    break
            taken = self._ring[self._cursor : self._cursor + int(self._credit) - len(due)]
            self._cursor += len(taken)
            due += taken
        self._credit -= len(due)
        return due

    def _full_listing(self, records, now):
        self._last_full = self._rolled_at = now
        self._restored = False  # every record is compared below
        self.last_reconcile_at = _wall()
        listing, present = self.watch.full_changes()
        if self._live is None:
            self._live = {
                k for k, r in records.items() if has_meta(r) and not _settled(r)
            }
        self._pending = {k for k in self._sigs if k not in present}
        return listing, [key for key in records if key not in present]

    def _full_due(self, now):
        if self._last_full is None:
            return True
        if self.journaled and self.full_sweep_sec:
            return False
        rolling = self.watch.rolling and not self.journaled
        if rolling and self._sigs_known and self.full_sweep_sec:
            return False
        return now - self._last_full >= self.full_sweep_sec

    def _may_change(self, records, key, sig, now):
        record = records.get(key)
        if record is None:
            return True
        if not has_meta(record):
            return False  # not an experiment (a legacy verinfo file)
        return self._changed_since(key, sig, now, _settled(record))

    def _changed_since(self, key, sig, now, settled):
        if not settled:
            return True
        if sig is not None and sig != self._sigs.get(key):
            return True
        return now - self._touched.get(key, float("-inf")) < self._touch_window()

    def _touch_window(self):
        return min(self.full_sweep_sec, TOUCH_WINDOW_SEC)
