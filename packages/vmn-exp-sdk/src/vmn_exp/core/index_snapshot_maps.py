#!/usr/bin/env python3
"""What an :class:`~vmn_exp.core.index_snapshot.IndexSnapshot` keys by
verstr, kept between snapshots by its
:class:`~vmn_exp.core.index_snapshot.RowCache`.

Each map is a :class:`~vmn_exp.core.shared_map.SharedMap`: the changes put
since the last snapshot are held aside and :meth:`SnapshotMaps.shared`
derives the next generation of each map from them alone (plan 26 F00), so a
generation that changed a few runs costs a few entries, not a copy of every
map.
"""
from vmn_exp.core.index_views import SIDE_TABLES, kept_side
from vmn_exp.core.shared_map import SharedMap

# The snapshot field each map fills.
_FIELDS = {"rows": "_by_verstr", "notes": "create_notes", "states": "run_states",
           "observed": "run_state_observed_at", "edges": "edges",
           **{name: name for name in SIDE_TABLES}}


class SnapshotMaps:
    def __init__(self):
        self._maps = {name: SharedMap() for name in _FIELDS}
        self._changes = {name: {} for name in _FIELDS}
        self._removed = {name: set() for name in SIDE_TABLES}

    def put(self, row, note, sides, state, observed):
        verstr, changes = row["verstr"], self._changes
        changes["rows"][verstr] = row
        changes["notes"][verstr] = note
        changes["states"][verstr] = state
        changes["observed"][verstr] = observed
        changes["edges"][verstr] = row.get("parent")
        for name, value in zip(SIDE_TABLES, sides):
            value = kept_side(name, value)
            if value:  # side tables are sparse: an empty value is no entry
                changes[name][verstr] = value
                self._removed[name].discard(verstr)
            else:
                changes[name].pop(verstr, None)
                self._removed[name].add(verstr)

    def shared(self):
        """``{snapshot field: SharedMap}`` with every change put so far."""
        for name, changes in self._changes.items():
            removed = self._removed.get(name, ())
            if changes or removed:
                self._maps[name] = self._maps[name].derive(changes, removed)
                self._changes[name] = {}
                if removed:
                    self._removed[name] = set()
        return {_FIELDS[name]: shared for name, shared in self._maps.items()}
