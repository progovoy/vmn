#!/usr/bin/env python3
"""A journaled index's journal mark, persisted with its records.

The mark is the change-journal position (the reader cursor's ``last_seen_ms``)
whose every entry the persisted records reflect (see
:meth:`~vmn_exp.core.index_sweep_behind.SweepBehind.persistable_mark`). It
lives in the cache store's key-value table under ``journal-mark:<app>``
(fingerprint :data:`FINGERPRINT`, payload ``{"ms": <mark>}``), written in the
transaction that saves the records when the store joins them, else right
after them — so it never vouches for records the store lacks. An idle index
rewrites it at most every :data:`SAVE_EVERY_MS`: a restart replaying a minute
more of the journal costs next to nothing.
"""
FINGERPRINT = "journal-mark-1"
SAVE_EVERY_MS = 60_000


class JournalMark:
    def __init__(self, store, app_name):
        self._store, self._scope = store, f"journal-mark:{app_name}"
        self._saved = None  # the mark as last persisted (or read)

    def load(self):
        """The persisted mark (ms), or None."""
        payload = self._store.kv_get(self._scope, FINGERPRINT)
        mark = payload.get("ms") if isinstance(payload, dict) else None
        if mark is not None:
            self._saved = max(self._saved or mark, mark)
        return mark

    def puts(self, mark, changed):
        """The kv put persisting *mark* (a list of none or one): due once it
        moved, at once when the records *changed* (it joins their save)."""
        saved = self._saved
        if mark is None or (saved is not None and mark <= saved):
            return []
        if not changed and saved is not None and mark - saved < SAVE_EVERY_MS:
            return []
        return [(self._scope, FINGERPRINT, {"ms": mark})]

    def saved(self, puts):
        """*puts* (from :meth:`puts`) were persisted."""
        if puts:
            self._saved = puts[-1][2]["ms"]
