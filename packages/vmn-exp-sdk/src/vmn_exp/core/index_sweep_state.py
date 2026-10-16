#!/usr/bin/env python3
"""What of a :class:`~vmn_exp.core.index_sweep.Sweep` outlives its process
(plan 25 §2, persisted by :mod:`~vmn_exp.core.index_baseline`).

A sweep runs on the caller's monotonic clock, which means nothing to another
process, so its times travel as wall times: when the last full listing ran
(the next one is due ``full_sweep_sec`` after it, whoever runs it) and when
each touched record last changed. The live and pending sets travel as they
are; a record that went live since was written to, which moved its signature.
What makes a record no longer live is :func:`_settled`'s call.
"""
from vmn_exp.core.status import RUNNING, derive_status, observed_at_from_mtime


class SweepState:
    def export_state(self, now, wall):
        """The sweep's state for a later process, in wall time *wall* (a
        monotonic clock does not cross processes; ms keep it from drifting
        between refreshes); see :meth:`restore_state`."""
        return {
            "last_full": round(wall - (now - self._last_full), 3),
            "touched": {k: round(wall - (now - t), 3) for k, t in self._touched.items()},
            "live": sorted(self._live), "pending": sorted(self._pending),
            "sigs_known": self._sigs_known, "names_at": self.watch.names_at,
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
        self.watch.names_at = state.get("names_at") if age >= 0 else None

    def _against_records(self, records, changed, gone):
        """The first listing after a restore also judges what the persisted
        records and the names disagree on: a record whose name is gone is
        removed, a listed name the records lack (nor wait for) is loaded."""
        self._restored = False
        missing = records.keys() - self._sigs.keys() - changed.keys()
        unknown = self._sigs.keys() - records.keys() - self._pending - gone
        return {**{k: self._sigs[k] for k in unknown}, **changed}, gone | missing


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
