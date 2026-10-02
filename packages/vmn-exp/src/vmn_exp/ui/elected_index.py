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
    def __init__(self, storage, app_name, cache_store, election):
        self.app_name = app_name
        self._election = election
        self._leader = ExperimentIndex(storage, app_name, cache_store=cache_store)
        self._follower = ExperimentIndex.follower(cache_store, app_name)
        self.leading = False

    @property
    def scope(self):
        return f"index:{self.app_name}"

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
