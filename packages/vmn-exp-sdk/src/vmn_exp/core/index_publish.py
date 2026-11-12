#!/usr/bin/env python3
"""How :class:`~vmn_exp.core.index.ExperimentIndex` applies what a refresh
read to its records and publishes a new snapshot of them: a bulk load's
publishing cadence, a follower's deltas (a mixin; all state stays on the
index). The storage order (``_sorted_keys``) stays in core/index.py, since
tests patch the ``_timestamp`` it reads there."""
from vmn_exp.core.index_follower import apply_delta
from vmn_exp.core.index_rows import adopted as _adopted


class IndexPublish:
    def _apply(self, results, removed, started):
        touched, new, redescribed = set(), [], False
        for key, record, dirty, moved, state_moved in results:
            old = self._records.get(key)
            if old is not None and (dirty or state_moved):
                self._sweep.touch(key, started)
            if record is None:
                continue  # the helper found nothing to change
            if old is None:
                new.append(key)
            elif moved:
                redescribed = True
            if old is None or dirty or state_moved:
                touched.add(key)
                self._sweep.track(key, record)
            if dirty:
                self._rows.pop(key, None)
            self._records[key] = _adopted(old, record, state_moved)
        for key in removed:
            del self._records[key]
            self._rows.pop(key, None)
            self._sweep.forget(key)
        self._unreadable.forget(removed)
        if not self._lean:
            self._publish(new, removed, redescribed, touched)

    def _publish(self, new, removed, redescribed, touched):
        """Publish what changed — while a bulk load has many records to go,
        only once due (:mod:`~vmn_exp.core.index_bulk`)."""
        bulk, backlog = self._bulk, self._backlog()
        self._number_later(backlog)
        if not backlog and self._sweep.relisted_new() is False:  # the bulk load is over
            self._close_loaders()
        bulk.add(new, removed, redescribed, touched)
        snap = self._snapshot
        if snap is None and not bulk.pending() and self._bulk_listing():
            return  # nothing loaded yet: requests get loading_snapshot meanwhile
        if snap is not None and backlog and not bulk.due(len(snap.rows), self._chunk()):
            return
        self._publish_pending()

    def _publish_pending(self):
        bulk, snap, started = self._bulk, self._snapshot, self._monotonic()
        new, resort, touched = bulk.take()
        # Only a new, removed or re-described record can move in the order.
        if new or resort or self._order is None:
            self._reorder = (new, resort)
            self._order = self._sorted_keys()
        if touched is None or touched or snap is None:
            self.generation += 1
            self._snapshot = self._build_snapshot(touched)
            bulk.published(started)

    def _backlog(self):
        """Whether a load has many records yet to read: more than a chunk of
        this refresh's past the current one, or of the new names a listing
        behind serving found and has not handed over."""
        new = self._sweep.relisted_new()
        return max(self._unread, new[2] if new else 0) > self._chunk()

    def _loading(self, rows):
        """``(rows loaded, rows expected)`` while a load reads many new
        records (expected None while a cold index's listing named none
        yet), else None."""
        new = self._sweep.relisted_new()
        if new is None:
            return (rows, None) if not self._records else None
        known, seen, left = new or (0, 0, 0)
        if self._unread or (seen > self._chunk() and left):
            return rows, max(known + seen, len(self._records) + self._unread)
        return None

    def _number_later(self, later):
        """While *later* (a bulk load prepending records, which would
        renumber every persisted row per chunk), let the store leave its
        rows' ``idx`` stale; once not, it numbers them (see
        :meth:`~vmn_exp.core.index_store.SqliteStore.number_later`)."""
        number_later = getattr(self._store, "number_later", None)
        if number_later is not None:
            number_later(self.app_name, later)

    def _publish_persisted(self):
        """Serve the records as persisted until the listing under way
        revalidates them."""
        self._order = self._sorted_keys()
        self.generation += 1
        self._snapshot, self._first_rows = self._build_snapshot(), None
        self._set_published()

    def _refresh_from_cache(self):
        if self._records is None:
            self._records = {}
        old = set(self._records)
        changed, removed, self._cache_gen = apply_delta(
            self._records, self._store, self.app_name, self._cache_gen
        )
        for key in changed | removed:
            self._rows.pop(key, None)
        new = [key for key in changed if key not in old]
        # A changed record may have been re-described (its timestamp moved).
        self._reorder = (new, bool(removed) or len(new) < len(changed))
        self._order = self._sorted_keys()
        if changed or removed or self._snapshot is None:
            self.generation += 1
            self._snapshot = self._build_snapshot(None if removed else changed)

    def _build_snapshot(self, touched=None):
        order = self._order or []
        self.published_at = self._monotonic()
        return self._rows.snapshot(
            self.app_name, self.generation, order, self._records, touched,
            self._loading(len(order)),
        )
