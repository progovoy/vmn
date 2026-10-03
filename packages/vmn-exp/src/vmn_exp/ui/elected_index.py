#!/usr/bin/env python3
"""One scope's index on a replica that shares a Postgres cache (plan 11 §4.3).

Each :meth:`ElectedIndex.refresh` asks the election whether this replica
leads the scope: the leader refreshes from the store and saves into the
shared cache; every other replica is a follower, applying that cache's
``load_since`` deltas without touching the store. A replica that takes over
reconciles first (its records may be stale from before it lost the lead).
"""
from vmn_exp.core.index import ExperimentIndex


class ElectedIndex:
    def __init__(self, storage, app_name, cache_store, election, workspace_id=0, org_id=None):
        self.app_name = app_name
        self.workspace_id = workspace_id
        self.org_id = org_id
        self._election = election
        self._cache_store = cache_store
        self._leader = ExperimentIndex(storage, app_name, cache_store=cache_store)
        self._follower = ExperimentIndex.follower(cache_store, app_name)
        self.leading = False

    @property
    def scope(self):
        return f"index:{self.org_id or 0}:{self.workspace_id}:{self.app_name}"

    @property
    def wake_key(self):
        """The ``vmn_gen`` payload its leader's saves notify."""
        return f"{self.workspace_id}:{self.app_name}"

    @property
    def full_sweep_sec(self):
        return self._leader.full_sweep_sec

    @full_sweep_sec.setter
    def full_sweep_sec(self, value):
        self._leader.full_sweep_sec = value

    @property
    def journaled(self):
        return self._leader.journaled

    @journaled.setter
    def journaled(self, value):
        self._leader.journaled = value

    @property
    def generation(self):
        return self._current().generation

    @property
    def record_count(self):
        return self._current().record_count

    @property
    def drift(self):
        return self._leader.drift

    @property
    def last_reconcile_at(self):
        return self._leader.last_reconcile_at

    def adopt(self, other, store=None):
        """A rebuild's records, persisted into the shared cache by default."""
        self._leader.adopt(other, store or self._cache_store)

    def hint(self, name):
        self._leader.hint(name)

    def reconcile(self):
        self._leader.reconcile()

    def refresh(self):
        leading = self._election.lead(self.scope)
        if leading and not self.leading:
            self._leader.reconcile()
        self.leading = leading
        self._current().refresh()
        return self

    def refresh_if_stale(self, max_age_sec):
        self.refresh()
        return self.snapshot()

    def snapshot(self):
        return self._current().snapshot()

    def _current(self):
        return self._leader if self.leading else self._follower
