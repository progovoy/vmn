#!/usr/bin/env python3
"""What a :class:`~vmn_exp.core.index_sweep.Sweep` gives back when the
refresh that took its listings fails (an S3 LIST answering ``SlowDown`` past
botocore's retries, a save the index store refuses).

A listing consumes state as it goes: hints, name signatures, the watch's
fingerprints, a due full listing. So the sweep remembers the keys a refresh
took — the hints, the records it asked the watch about, those it handed over
or reported gone — and :meth:`SweepRetake.failed` lists them again as hints
(always listed and handed over, even unchanged), their fingerprints dropped
so a slice or full listing reports them again too. A full listing is redone
whole instead (record by record, an S3 store's would be three LISTs a record,
not one per 1000 objects). Nothing else is listed again: forgetting every baseline instead made the next refresh re-list the
whole store, more of the requests it was refusing (at ~490k S3 records,
hours of LISTs).
"""


class SweepRetake:
    _mark_before = None  # the journal mark when the last refresh succeeded
    _listed_full = None  # what this refresh's full listing reported changed

    def applied(self):
        """The refresh that took the listings since the last call succeeded."""
        self._taken, self._mark_before, self._listed_full = set(), self.mark_taken, None

    def _took(self, *keys):
        for some in keys:
            self._taken.update(some)

    def failed(self):
        """The refresh that took the listings since the last :meth:`applied`
        failed before it applied and persisted all of them: list what they
        took again, from the journal mark it had."""
        taken, self._taken = self._taken, set()
        with self._hint_lock:
            self._hinted.update(taken)
        self.mark_taken = self._mark_before
        if self._listed_full is not None:
            self._last_full = None
            taken.update(self._listed_full)
            self._listed_full = None
        self.watch.forget(taken)
