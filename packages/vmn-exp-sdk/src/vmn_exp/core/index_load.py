#!/usr/bin/env python3
"""How :class:`~vmn_exp.core.index.ExperimentIndex` loads what a listing
hands a refresh: chunk by chunk (newest first, their ancestors next) on a
remote store, rows-first, with the listing behind serving and an upgrade's
re-derive in between (a mixin; all state stays on the index)."""
from dataclasses import replace

from vmn_exp.core import index_freshness
from vmn_exp.core.gc_pause import gc_paused
from vmn_exp.core.index_bulk import loading_snapshot
from vmn_exp.core.index_first_rows import kept_snapshot
from vmn_exp.core.index_load_queue import LoadQueue
from vmn_exp.core.index_rows_first import first_objects
from vmn_exp.core.index_sweep import METADATA_FILE

# How long a refresh of a cold remote index keeps loading what its listing
# behind serving hands over before letting the next refresh serve the
# journal's hints (and the ui see the refresh end, not a stuck one).
BEHIND_REFRESH_SEC = 30.0
# Seconds between the empty snapshots a re-derive publishes its progress in.
MIGRATING_PUBLISH_SEC = 1.0


def _listed_at(work_item):
    """When the listing saw *work_item*'s metadata.yml written (a remote
    backend's ``(size, mtime, etag)`` signature), 0 when it does not say."""
    sig = work_item[1].get(METADATA_FILE)
    return sig[1] if isinstance(sig, (list, tuple)) and len(sig) > 1 else 0


class IndexLoad:
    def _more_relisted(self, started):
        """Whether to load more of what a listing behind serving hands over
        in this refresh: during a bulk load (a cold index's) the next batch
        is waited for, up to BEHIND_REFRESH_SEC into the refresh — unless a
        journal hint waits for the next refresh."""
        while True:
            left = BEHIND_REFRESH_SEC - (self._monotonic() - started)
            if left <= 0 or self._sweep.hints_waiting():
                return False
            if self._sweep.relisted_ready():
                return True
            if not self._bulk_listing():
                return False
            self._sweep.wait_relisted(min(left, 1.0))

    def _bulk_listing(self):
        """Whether a listing behind serving brings many new records (a cold
        index's), not all handed over yet."""
        new = self._sweep.relisted_new()
        return new is None or bool(new and new[1] > self._chunk() and new[2])

    def _load_listed(self, listing, removed, started):
        # Unfinished claims and deleted records' leftovers have no metadata.
        refold = self._vmx.refold
        work = [
            (key, names, self._listed_record(key))
            for key, names in listing.items()
            if METADATA_FILE in names
        ]
        self._load_work(work, removed, started)
        self._vmx.refolded({k for k in refold.intersection(listing) if k not in self._unreadable})

    def _listed_record(self, key):
        """The record a listing of *key* refreshes: None (read afresh, whole)
        for one an upgrade's check found wrong (index_vmx_check)."""
        return None if key in self._vmx.refold else self._records.get(key)

    def _load_work(self, work, removed, started):
        unread = sum(record is None for _, _, record in work)
        self._freshness.loading(unread)
        if self._io is not None:  # the helper process persists them
            results = self._io.refresh(work, removed)
            self._io_unreadable = self._io.unreadable()
            self._apply(results, removed, started)
            self._save_mark(self._mark_puts(results, removed))
            return
        queue = self._load_queue(work)
        self._unread = unread
        try:
            chunk = self._take(queue)
            while queue:
                new = sum(record is None for _, _, record in chunk)
                self._unread -= new
                results = self._refresh_part(chunk, (), started, None)
                self._freshness.loaded(new)
                queue.want(self._unloaded_parents(results))
                chunk = self._take(queue)
        finally:
            self._unread = 0
        self._refresh_part(chunk, removed, started, started)

    def _derive_first(self, serve_kept=True):
        """Rows an upgrade left to re-derive are, from the persisted records
        (:mod:`~vmn_exp.core.index_derive`, no storage read), before they
        load; meanwhile the rows the upgrade kept (stale) or else an empty
        snapshot serve, ``loading`` the share done (republished at most every
        MIGRATING_PUBLISH_SEC; with an I/O helper, which owns the files and
        sends no progress, once). *serve_kept* False: none (an I/O helper's
        index, whose snapshots nobody reads). Whether any were."""
        io = self._io
        if io is None:
            deriving = getattr(self._store, "deriving", None)
            if deriving is None or not deriving(self.app_name):
                return False
        elif (total := io.deriving()) is None:
            return False
        if serve_kept and not self._lean:
            if self._first_rows is None:  # none of the newest: their total, at once
                self._first_rows = loading_snapshot(self.app_name, total if io is not None
                                                    else self._store.count(self.app_name))
                self._servable.set()
            with gc_paused():
                self._kept = kept_snapshot(self.app_name, io.kept() if io is not None
                                           else self._kept_parts())
        try:
            if io is None:
                self._store.derive(self.app_name, self._derived)
            else:  # the helper owns the files; no progress crosses
                self._derived(0, total)
                io.derive()
        finally:
            self._kept = None
        return True

    def _derived(self, done, total):
        self._freshness.migrating(done, total)
        if self._lean or (self._snapshot is not None
                          and self._monotonic() - self.published_at < MIGRATING_PUBLISH_SEC):
            return
        self.generation += 1
        if self._kept is not None:  # the kept rows, stale until re-derived
            self._snapshot = replace(self._kept, generation=self.generation,
                                     loading=(done, total))
        else:
            self._snapshot = self._rows.snapshot(
                self.app_name, self.generation, [], {}, loading=(done, total))
        self.published_at = self._monotonic()
        self._set_published()

    def _listing_phase(self, now):
        sweep = self._sweep
        if sweep._full_due(now) and not (sweep.journaled and sweep.behind):  # see freshness()
            return index_freshness.FULL_LISTING
        return index_freshness.JOURNAL if self._sweep.journaled else index_freshness.LISTING

    def _listing_position(self):
        """``position()`` -> the key a full listing's walk is at, when the
        storage tells (:meth:`~vmn_exp.storage.s3_listing.S3Listing.listing_position`)."""
        position_of = getattr(self._storage, "listing_position", None)
        return (lambda: position_of(self.app_name)) if position_of else None

    def _take(self, queue):
        """The queue's next chunk, a remote record not read yet cut to its
        row's files (:func:`first_objects`), its rest queued for later — during
        a bulk load behind serving, until its listing is over (then hinted)."""
        chunk = [(key, names, self._listed_record(key)) for key, names, _ in queue.take()]
        if not self._remote():
            return chunk
        cut, rest = [], []
        for key, names, record in chunk:
            if key in self._vmx.refold:  # whole, never rows-first: its row serves meanwhile
                cut.append((key, names, record))
                continue
            if record is None and queue.put_off(key):
                continue  # its row's part was set aside unread: read when due
            first = first_objects(names) if record is None else None
            cut.append((key, names if first is None else first, record))
            if first is not None:
                rest.append((key, names, None))
        if rest and self._bulk_listing():
            self._rests.update(key for key, _, _ in rest)
        else:
            queue.later(rest)
        return cut

    def _load_queue(self, work):
        """*work* queued so a remote cold load serves and keeps its records a
        chunk at a time, the newest first (their ancestors next), rather than
        only once every record was read."""
        if not work or not self._remote():
            return LoadQueue(work, len(work))
        return LoadQueue(sorted(work, key=_listed_at, reverse=True), self._chunk())

    def _unloaded_parents(self, results):
        parents = ((record.get("meta") or {}).get("parent")
                   for _, record, _, _, _ in results if record is not None)
        return [p for p in parents if p and self._records.get(p) is None]

    def _refresh_part(self, work, removed, started, baseline_at):
        """Read, apply and persist *work*, with the listing baseline as of
        *baseline_at* (None: not the refresh's last part)."""
        results = self._refresh_local(work)
        with gc_paused():
            try:
                self._apply(results, removed, started)
            except BaseException:
                self._persist(results, removed)  # no baseline: the sweep missed some
                raise
            self._persist(results, removed, baseline_at)
        if self._snapshot is not None:
            self._set_published()
        return results
