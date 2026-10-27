#!/usr/bin/env python3
"""What an :class:`vmn_exp.core.index.ExperimentIndex` refreshed but could
not persist yet (plan 25 §2: a failed save marks its records dirty again).

A refresh hands its changes to :meth:`PendingSave.save`, which saves them
together with whatever an earlier failed save left behind; when the store
answers False they all stay pending for the next refresh. The pending
records are the refreshed objects themselves, so a later save writes their
latest content.

A save is :data:`SAVE_CHUNK` records per store transaction (removals and
``kv_puts`` with the last), so none holds a whole cold load and its WAL
(the I/O helper process persists a cold refresh in one call); a failed part
leaves itself and the parts after it pending.
"""

SAVE_CHUNK = 500  # records per save transaction


class PendingSave:
    def __init__(self):
        self._changed, self._removed, self._states = {}, set(), {}

    @property
    def pending(self):
        """Whether an earlier save left something unpersisted."""
        return bool(self._changed or self._removed or self._states)

    def save(self, store, scope, changed, removed, states, kv_puts=None):
        """Save these changes and the pending ones into *store* (with
        *kv_puts*, for a store that ``JOINS_KV``), a chunk at a time;
        whether all of it saved."""
        if self.pending:
            changed, removed, states = self._with_pending(changed, set(removed), states)
        parts = _parts(list(dict.fromkeys([*changed, *states])))
        for n, keys in enumerate(parts):
            last = n == len(parts) - 1
            extra = {"kv_puts": kv_puts} if kv_puts and last else {}
            saved = store.save(scope, _only(changed, keys), set(removed) if last else set(),
                               _only(states, keys), **extra)
            if saved is False:
                rest = [key for part in parts[n:] for key in part]
                self._changed, self._states = _only(changed, rest), _only(states, rest)
                self._removed = set(removed)
                return False
        self._changed, self._removed, self._states = {}, set(), {}
        return True

    def _with_pending(self, changed, removed, states):
        return (
            _merged(self._changed, changed, removed),
            (self._removed - set(changed)) | removed,
            _merged(self._states, states, removed),
        )


def _parts(keys):
    """*keys* :data:`SAVE_CHUNK` at a time; one (empty) part without keys."""
    return [keys[i:i + SAVE_CHUNK] for i in range(0, len(keys), SAVE_CHUNK)] or [[]]


def _only(records, keys):
    return {key: records[key] for key in keys if key in records}


def _merged(pending, new, removed):
    out = {key: record for key, record in pending.items() if key not in removed}
    out.update(new)
    return out
