#!/usr/bin/env python3
"""How :class:`~vmn_exp.core.index.ExperimentIndex` reads its records back
from its store and saves what a refresh changed, with the listing baseline
and the journal mark (a mixin; all state stays on the index)."""


class IndexPersist:
    def _keeps_baseline(self):
        """Whether listing baselines persist: not for a journaled sweep, one
        whose listings run in the I/O helper process, or one listing fully
        every time (nothing to carry on from)."""
        return self._io is None and not self._sweep.journaled and bool(self.full_sweep_sec)

    def _load_records(self):
        if self._io:
            return self._io.load()
        lazy_of = getattr(self._store, "load_lazy", None) if self._lean else None
        lazy = lazy_of(self.app_name) if lazy_of else None
        if lazy is not None:
            return lazy
        warm = getattr(self._store, "load_warm", None)
        loaded = warm(self.app_name) if warm else None
        if loaded is None:
            self._cold = True
            return self._store.load(self.app_name)
        records, self._order, lean, self._stamps = loaded
        self._rows.seed(lean)
        return records

    def _refresh_and_persist(self, work, removed):
        """``(key, record, dirty, moved, state moved)`` per item of *work*,
        persisted with *removed*: what the helper process's index answers
        (``None`` records stand for those it found unchanged)."""
        results = self._refresh_local(work)
        self._persist(results, removed)
        self._unreadable.forget(removed)
        return results

    def _persist(self, results, removed, started=None):
        """Save *results* with *removed*, then — given the refresh's
        *started* — the listing baseline: in the same transaction when the
        store joins them, else only once nothing is left unsaved."""
        baseline = started is not None and self._keeps_baseline()
        joins = getattr(self._store, "JOINS_KV", False)
        joint = baseline and joins
        puts = self._baseline.puts(self._sweep, started) if joint else None
        marks = self._mark_puts(results, removed) if started is not None else []
        saved = self._unsaved.save(
            self._store, self.app_name,
            {key: record for key, record, dirty, _, _ in results if dirty},
            removed,
            {key: record for key, record, _, _, state_moved in results if state_moved},
            (puts or []) + marks if joins else puts,
        )
        if puts and not saved:
            self._baseline.forget()
        elif baseline and not joint and saved:
            self._baseline.save(self._sweep, started)
        if saved:
            self._mark.saved(marks) if joins else self._save_mark(marks)

    def _mark_puts(self, results, removed):
        changed = bool(removed) or any(dirty or state_moved for _, _, dirty, _, state_moved in results)
        return self._mark.puts(self._sweep.persistable_mark(), changed)

    def _save_mark(self, puts):
        for put in puts:
            self._store.kv_put(*put)
        self._mark.saved(puts)
