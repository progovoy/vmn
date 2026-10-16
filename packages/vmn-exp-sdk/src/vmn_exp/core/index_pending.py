#!/usr/bin/env python3
"""What an :class:`vmn_exp.core.index.ExperimentIndex` refreshed but could
not persist yet (plan 25 §2: a failed save marks its records dirty again).

A refresh hands its changes to :meth:`PendingSave.save`, which saves them
together with whatever an earlier failed save left behind; when the store
answers False they all stay pending for the next refresh. The pending
records are the refreshed objects themselves, so a later save writes their
latest content.
"""


class PendingSave:
    def __init__(self):
        self._changed, self._removed, self._states = {}, set(), {}

    @property
    def pending(self):
        """Whether an earlier save left something unpersisted."""
        return bool(self._changed or self._removed or self._states)

    def save(self, store, scope, changed, removed, states):
        """Save these changes and the pending ones into *store*."""
        if self.pending:
            changed, removed, states = self._with_pending(changed, set(removed), states)
        if store.save(scope, changed, removed, states) is False:
            self._changed, self._removed, self._states = dict(changed), set(removed), dict(states)
        else:
            self._changed, self._removed, self._states = {}, set(), {}

    def _with_pending(self, changed, removed, states):
        return (
            _merged(self._changed, changed, removed),
            (self._removed - set(changed)) | removed,
            _merged(self._states, states, removed),
        )


def _merged(pending, new, removed):
    out = {key: record for key, record in pending.items() if key not in removed}
    out.update(new)
    return out
