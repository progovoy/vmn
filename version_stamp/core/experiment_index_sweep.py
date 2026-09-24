#!/usr/bin/env python3
"""Which records an :mod:`experiment_index` refresh lists the files of.

Stat-ing every file of every record on each refresh costs seconds at a few
thousand runs. So a refresh lists record *names* only (the backend's
``list_record_names``), then the files of just the records that can have
changed: new ones, live ones (no run state, no exit code yet) and ones seen
changing within the last ``full_sweep_sec`` — a run's last metrics may land
after its exit code. Every ``full_sweep_sec``, and always for a backend without
names-only listing, one full ``list_files`` catches the rest (a note edited on
a long-finished run, a record removed only partly).
"""
from version_stamp.core.experiment_status import FAILED, SUCCEEDED, derive_status

METADATA_FILE = "metadata.yml"
DEFAULT_FULL_SWEEP_SEC = 300


def _finished(run_state):
    try:
        return derive_status(run_state) in (SUCCEEDED, FAILED)
    except (TypeError, ValueError):  # a hand-edited, unparseable exit code
        return False


class Sweep:
    """The listing policy of one index; times are the caller's monotonic clock."""

    def __init__(self, storage, app_name, full_sweep_sec=DEFAULT_FULL_SWEEP_SEC):
        self._storage = storage
        self._app_name = app_name
        self._full_sweep_sec = full_sweep_sec
        self._last_full = None
        self._touched = {}  # key -> when a refresh last saw it change

    def touch(self, key, now):
        self._touched[key] = now

    def forget(self, key):
        self._touched.pop(key, None)

    def listing(self, records, now):
        """``(files of the records to refresh, keys of every present record)``."""
        names_of = getattr(self._storage, "list_record_names", None)
        if names_of is None or self._full_due(now):
            self._last_full = now
            listing = self._storage.list_files(self._app_name)
            return listing, {k for k, names in listing.items() if METADATA_FILE in names}
        present = names_of(self._app_name)
        keys = [key for key in present if self._may_change(records.get(key), key, now)]
        listing = self._storage.list_files(self._app_name, keys=keys) if keys else {}
        gone = {key for key in keys if METADATA_FILE not in listing.get(key, {})}
        return listing, present - gone

    def _full_due(self, now):
        return self._last_full is None or now - self._last_full >= self._full_sweep_sec

    def _may_change(self, record, key, now):
        if record is None:
            return True
        if record["meta"] is None:
            return False  # not an experiment (a legacy verinfo file)
        if not _finished(record["run_state"]):
            return True
        return now - self._touched.get(key, float("-inf")) < self._full_sweep_sec
