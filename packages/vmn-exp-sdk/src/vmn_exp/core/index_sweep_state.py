#!/usr/bin/env python3
"""What of a :class:`~vmn_exp.core.index_sweep.Sweep` outlives its process
(plan 25 §2, persisted by :mod:`~vmn_exp.core.index_baseline`).

A sweep runs on the caller's monotonic clock, which means nothing to another
process, so its times travel as wall times: when the last full listing ran
(the next one is due ``full_sweep_sec`` after it, whoever runs it) and when
each touched record last changed. The live and pending sets travel as they
are; a record that went live since was written to, which moved its signature.
"""


class SweepState:
    def export_state(self, now, wall):
        """The sweep's state for a later process, in wall time *wall* (a
        monotonic clock does not cross processes; ms keep it from drifting
        between refreshes); see :meth:`restore_state`."""
        return {
            "last_full": round(wall - (now - self._last_full), 3),
            "touched": {k: round(wall - (now - t), 3) for k, t in self._touched.items()},
            "live": sorted(self._live), "pending": sorted(self._pending),
            "sigs_known": self._sigs_known,
        }

    def restore_state(self, state, sigs, now, wall):
        """Carry on from *state* (:meth:`export_state`) and the name *sigs*
        the watch was restored to; a clock gone backwards makes a full
        listing due."""
        age = wall - state["last_full"]
        self._last_full = now - age if age >= 0 else None
        self._touched = {k: now - (wall - t) for k, t in state["touched"].items()}
        self._live, self._pending = set(state["live"]), set(state["pending"])
        self._sigs_known, self._sigs, self._restored = state["sigs_known"], dict(sigs), True

    def _against_records(self, records, changed, gone):
        """The first listing after a restore also judges what the persisted
        records and the names disagree on: a record whose name is gone is
        removed, a listed name the records lack (nor wait for) is loaded."""
        self._restored = False
        missing = records.keys() - self._sigs.keys() - changed.keys()
        unknown = self._sigs.keys() - records.keys() - self._pending - gone
        return {**{k: self._sigs[k] for k in unknown}, **changed}, gone | missing
