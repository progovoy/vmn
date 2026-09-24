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

The fast tier is opt-in: ``full_sweep_sec`` defaults to 0, where every refresh
is a full listing and an in-place write by anyone shows up at once. A server
that refreshes often sets it (a mutable attribute) and sweeps in the background.
"""
from version_stamp.core.experiment_status import (
    RUNNING,
    derive_status,
    observed_at_from_mtime,
)

METADATA_FILE = "metadata.yml"
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


def _as_sigs(names):
    """``{name: sig}`` from a backend's answer; None stays None."""
    if names is None or isinstance(names, dict):
        return names
    return dict.fromkeys(names)


class Sweep:
    """The listing policy of one index; times are the caller's monotonic clock."""

    def __init__(self, storage, app_name, full_sweep_sec=DEFAULT_FULL_SWEEP_SEC):
        self._storage = storage
        self._app_name = app_name
        self.full_sweep_sec = full_sweep_sec
        self._last_full = None
        self._touched = {}  # key -> when a refresh last saw it change
        self._sigs = {}  # key -> its sig at the last listing
        self._sigs_known = True  # False once the backend answered only None sigs

    def touch(self, key, now):
        self._touched[key] = now

    def forget(self, key):
        self._touched.pop(key, None)
        self._sigs.pop(key, None)

    def listing(self, records, now):
        """``(files of the records to refresh, keys of every present record)``."""
        names_of = getattr(self._storage, "list_record_names", None)
        # Sigs are kept even while every refresh is full, so switching the
        # fast tier on later does not re-list every record once — unless the
        # backend has no sigs to give (S3), where asking is a wasted listing.
        if not self.full_sweep_sec and not self._sigs_known:
            names_of = None
        sigs = _as_sigs(names_of(self._app_name)) if names_of else None
        if sigs:
            self._sigs_known = any(sig is not None for sig in sigs.values())
        if sigs is None or self._full_due(now):
            return self._full_listing(sigs or {}, now)
        keys = [key for key, sig in sigs.items() if self._may_change(records, key, sig, now)]
        self._sigs = sigs
        listing = self._storage.list_files(self._app_name, keys=keys) if keys else {}
        gone = {key for key in keys if METADATA_FILE not in listing.get(key, {})}
        return listing, set(sigs) - gone

    def _full_listing(self, sigs, now):
        # Sigs taken before the listing: a write racing it shows up next time.
        self._last_full, self._sigs = now, sigs
        listing = self._storage.list_files(self._app_name)
        return listing, {k for k, names in listing.items() if METADATA_FILE in names}

    def _full_due(self, now):
        return self._last_full is None or now - self._last_full >= self.full_sweep_sec

    def _may_change(self, records, key, sig, now):
        record = records.get(key)
        if record is None:
            return True
        if record["meta"] is None:
            return False  # not an experiment (a legacy verinfo file)
        if not _settled(record):
            return True
        if sig is not None and sig != self._sigs.get(key):
            return True
        return now - self._touched.get(key, float("-inf")) < self.full_sweep_sec
