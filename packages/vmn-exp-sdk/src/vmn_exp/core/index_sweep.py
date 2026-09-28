#!/usr/bin/env python3
"""Which records an :mod:`experiment_index` refresh lists the files of.

Stat-ing every file of every record on each refresh costs seconds at a few
thousand runs. So a refresh asks the backend's ``list_record_names`` for
``{name: sig}`` — a cheap per-record signature (the local record directory's
mtime and inode, which every atomic write bumps), or None where the backend
cannot know — and lists the files of just the records that can have changed:
new ones, running ones (only a fresh heartbeat can still move on its own),
and every other status — ``created``, ``stuck``, ``succeeded``, ``failed`` —
only once its sig moved or it changed within the last ``full_sweep_sec`` (a
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
every new run, waiting for seconds.

The fast tier is opt-in: ``full_sweep_sec`` defaults to 0, where every refresh
is a full listing and an in-place write by anyone shows up at once. A server
that refreshes often sets it (a mutable attribute) and sweeps in the background.
"""
from vmn_exp.core.index_listing import METADATA_FILE, ListingWatch, as_sigs  # noqa: F401
from vmn_exp.core.status import (
    RUNNING,
    derive_status,
    observed_at_from_mtime,
)

DEFAULT_FULL_SWEEP_SEC = 0  # 0: every refresh is a full listing


def _observed_at(rs_sig):
    """The run state file's storage mtime from its ``[size, mtime, ...]``
    signature (mirrors :mod:`experiment_index_snapshot`'s own reading of it)
    — the store-side clock ``derive_status`` wants for clock-skew-proof
    ``stuck`` detection."""
    return observed_at_from_mtime(rs_sig[1]) if rs_sig and len(rs_sig) > 1 else None


def _settled(record):
    """False only for ``running``: every other status will not change on its
    own, so it may drop to the reduced re-listing rate (sig-diff + the
    touched window) instead of being listed on every fast cycle forever.

    ``stuck`` is included: it is not going to recover by itself, and if it
    somehow does (a write resuming it), that write bumps the record's
    directory signature, which the caller's sig-diff check still catches on
    the very next cycle regardless of status.
    """
    try:
        status = derive_status(record["run_state"], observed_at=_observed_at(record.get("rs_sig")))
    except (TypeError, ValueError):  # a hand-edited, unparseable exit code
        return False
    return status != RUNNING


class Sweep:
    """The listing policy of one index; times are the caller's monotonic clock."""

    def __init__(self, storage, app_name, full_sweep_sec=DEFAULT_FULL_SWEEP_SEC, watch=None):
        self.full_sweep_sec = full_sweep_sec
        self.watch = watch or ListingWatch(storage, app_name)
        self._last_full = None
        self._touched = {}  # key -> when a refresh last saw it change
        self._sigs = {}  # key -> its sig at the last listing
        self._sigs_known = True  # False once the backend answered only None sigs
        self._live = None  # keys that may change on their own; None: not judged yet
        self._pending = set()  # names listed without metadata yet (claims)
        self._ring, self._cursor, self._credit, self._rolled_at = [], 0, 0.0, None

    def reset(self):
        """Forget every baseline: the next listing is full and compares all."""
        self.watch.reset()
        self._last_full, self._sigs, self._live, self._pending = None, {}, None, set()
        self._ring, self._cursor, self._credit, self._rolled_at = [], 0, 0.0, None

    def touch(self, key, now):
        self._touched[key] = now

    def track(self, key):
        """*key*'s record was (re)loaded: judge it again at the next listing."""
        if self._live is not None:
            self._live.add(key)

    def forget(self, key):
        self._touched.pop(key, None)
        self._sigs.pop(key, None)
        self._pending.discard(key)
        if self._live is not None:
            self._live.discard(key)

    def listing(self, records, now):
        """``(files of the records to refresh, keys of records gone)``."""
        changes = self._name_changes()
        if changes is None or self._full_due(now):
            if changes is not None:
                self._apply_sigs(*changes)
            return self._full_listing(records, now)
        changed, gone_names = changes
        keys = self._to_list(records, changed, gone_names, now)
        listing = self.watch.files(keys)
        gone = {key for key in keys if METADATA_FILE not in listing.get(key, {})}
        if self.watch.rolling and self.full_sweep_sec:
            rolled, rolled_gone = self.watch.slice_changes(self._next_slice(now))
            listing = {**rolled, **listing}
            gone |= rolled_gone
        self._pending = {key for key in gone if key in self._sigs and key not in records}
        return listing, [key for key in gone | gone_names if key in records]

    def _name_changes(self):
        # Sigs are kept even while every refresh is full, so switching the
        # fast tier on later does not re-list every record once — unless the
        # backend has no sigs to give (S3), where asking is a wasted listing.
        if not self.full_sweep_sec and not self._sigs_known:
            return None
        changes = self.watch.name_changes()
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
            k: t for k, t in self._touched.items() if now - t < self.full_sweep_sec
        }
        candidates = (set(changed) | self._pending | self._live | set(self._touched)) - gone
        keys = []
        for key in candidates:
            if self._judge(records, key, changed.get(key, self._sigs.get(key)), now):
                keys.append(key)
        self._apply_sigs(changed, gone)
        return keys

    def _judge(self, records, key, sig, now):
        """:meth:`_may_change`, keeping the live set current on the way."""
        record = records.get(key)
        if record is None or record["meta"] is None:
            self._live.discard(key)
            return record is None
        settled = _settled(record)
        (self._live.discard if settled else self._live.add)(key)
        return self._changed_since(key, sig, now, settled)

    def _next_slice(self, now):
        """The known keys due for their periodic re-listing. A refresh lists
        at most a tenth of them, however long the last one took (a cold load
        can outlast full_sweep_sec)."""
        elapsed = now - (self._rolled_at if self._rolled_at is not None else now)
        elapsed = min(elapsed, self.full_sweep_sec / 10)
        self._rolled_at = now
        self._credit = min(
            self._credit + len(self._sigs) * elapsed / self.full_sweep_sec, len(self._sigs)
        )
        due = []
        while len(due) < int(self._credit):
            if self._cursor >= len(self._ring):
                self._ring, self._cursor = sorted(self._sigs), 0
            taken = self._ring[self._cursor : self._cursor + int(self._credit) - len(due)]
            self._cursor += len(taken)
            due += taken
        self._credit -= len(due)
        return due

    def _full_listing(self, records, now):
        self._last_full = self._rolled_at = now
        listing, present = self.watch.full_changes()
        if self._live is None:
            self._live = {
                k for k, r in records.items() if r["meta"] is not None and not _settled(r)
            }
        self._pending = {k for k in self._sigs if k not in present}
        return listing, [key for key in records if key not in present]

    def _full_due(self, now):
        if self._last_full is None:
            return True
        if self.watch.rolling and self._sigs_known and self.full_sweep_sec:
            return False
        return now - self._last_full >= self.full_sweep_sec

    def _may_change(self, records, key, sig, now):
        record = records.get(key)
        if record is None:
            return True
        if record["meta"] is None:
            return False  # not an experiment (a legacy verinfo file)
        return self._changed_since(key, sig, now, _settled(record))

    def _changed_since(self, key, sig, now, settled):
        if not settled:
            return True
        if sig is not None and sig != self._sigs.get(key):
            return True
        return now - self._touched.get(key, float("-inf")) < self.full_sweep_sec
