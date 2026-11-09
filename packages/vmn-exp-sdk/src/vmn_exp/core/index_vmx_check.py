#!/usr/bin/env python3
"""The background check an upgrade leaves for records that may not read right.

An upgrade in place (:mod:`vmn_exp.core.index_store_upgrade`) keeps the
records :data:`~vmn_exp.core.index_store_schema.CHECKED_RECORDS` picks and
lists their keys in the store's key-value table: ``vmx-check:<app>`` the
sorted keys (written once, joining what an earlier upgrade left unchecked),
``vmx-check-at:<app>`` how many are checked (rewritten per step, small).
Each refresh of the app's index runs a step of the check (:class:`VmxCheck`)
when one is due — at most every :data:`CHECK_EVERY_SEC`, for at most about
:data:`CHECK_BUDGET_SEC`, :data:`CHECK_WORKERS` records at a time — so the
refresh thread stays the server's, and the rows serve meanwhile. A record
the check finds wrong (:func:`~vmn_exp.core.vmx_check.needs_refold`) is
listed under ``vmx-refold:<app>`` before the cursor moves past it, then
hinted: its next refresh folds it afresh from storage, and only once that is
saved does it leave the list. A death part way loses nothing: the next load
resumes the cursor and hints the refolds left. The index's freshness says
``checking {done, total}`` until the list is done.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.core.index_store_kv import read_payload
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.core.vmx_check import needs_refold

FINGERPRINT = "vmx-check-1"
KEYS, AT, REFOLD = "vmx-check:", "vmx-check-at:", "vmx-refold:"
BACKGROUND = True  # refreshes run the check's steps (tests run them by hand)
CHECK_EVERY_SEC = 2.0
CHECK_BUDGET_SEC = 1.0
CHECK_WORKERS = 8


def puts(conn, keys):
    """The kv puts listing *keys* (``(app, key)`` pairs) to check, beside
    those an earlier upgrade left unchecked, the cursor back at 0."""
    by_app = {}
    for app, key in keys:
        by_app.setdefault(app, set()).add(key)
    out = []
    for app, names in by_app.items():
        listed = read_payload(conn, KEYS + app, FINGERPRINT) or []
        done = (read_payload(conn, AT + app, FINGERPRINT) or {}).get("done", 0)
        out += [(KEYS + app, FINGERPRINT, sorted(names.union(listed[done:]))),
                (AT + app, FINGERPRINT, {"done": 0})]
    return out


def indexed_objects(record):
    """``{name: size}`` of the ``.vmx`` objects *record*'s fold read."""
    objects = (record.get("metrics") or {}).get("objects") or {}
    return {name: size for name, size in objects.items() if is_indexed_file(name)}


class VmxCheck:
    """One app's check: *kv()* the store (or I/O helper) holding its lists."""

    def __init__(self, kv, app_name, clock=time.monotonic):
        self._kv, self._app, self._clock = kv, app_name, clock
        self._keys, self.done, self.refold = [], 0, set()
        self._due = 0.0

    def load(self):
        """Read the lists; the keys left to fold again."""
        kv = self._kv()
        self._keys = kv.kv_get(KEYS + self._app, FINGERPRINT) or []
        self.done = (kv.kv_get(AT + self._app, FINGERPRINT) or {}).get("done", 0)
        self.refold = set(kv.kv_get(REFOLD + self._app, FINGERPRINT) or ())
        return set(self.refold)

    def state(self):
        """``{done, total}`` while keys are left to check, else None."""
        total = len(self._keys)
        return {"done": self.done, "total": total} if self.done < total else None

    def due(self):
        return BACKGROUND and self.state() is not None and self._clock() >= self._due

    def step(self, storage, records, hint, limit=None):
        """Check keys from the cursor — *limit* of them, else for about
        :data:`CHECK_BUDGET_SEC` — reading *records* (``{key: record}``);
        *hint* each one to fold again. How many were checked."""
        started, checked = self._clock(), 0
        with ThreadPoolExecutor(CHECK_WORKERS, thread_name_prefix="vmn-vmx-check") as pool:
            while self.state() is not None and (limit is None or checked < limit):
                if limit is None and self._clock() - started >= CHECK_BUDGET_SEC:
                    break
                size = CHECK_WORKERS if limit is None else min(CHECK_WORKERS, limit - checked)
                chunk = self._keys[self.done:self.done + size]
                # A lazy record reads its stored head here, never on the pool's threads.
                objects = [indexed_objects(records.get(key) or {}) for key in chunk]
                found = list(pool.map(lambda item: self._wrong(storage, *item), zip(chunk, objects)))
                self._advance(len(chunk), [k for k, wrong in zip(chunk, found) if wrong], hint)
                checked += len(chunk)
        self._due = self._clock() + CHECK_EVERY_SEC
        return checked

    def _wrong(self, storage, key, objects):
        return bool(objects) and needs_refold(storage, (self._app, key), objects)

    def _advance(self, count, wrong, hint):
        kv = self._kv()
        if wrong:  # listed before the cursor moves past them
            self.refold.update(wrong)
            kv.kv_put(REFOLD + self._app, FINGERPRINT, sorted(self.refold))
        self.done += count
        kv.kv_put(AT + self._app, FINGERPRINT, {"done": self.done})
        if self.state() is None:
            kv.kv_put(KEYS + self._app, FINGERPRINT, None)
            self._keys, self.done = [], 0
            kv.kv_put(AT + self._app, FINGERPRINT, None)
        for key in wrong:
            hint(key)

    def refolded(self, keys):
        """*keys* were folded afresh and saved: off the refold list."""
        left = self.refold.difference(keys)
        if left != self.refold:
            self.refold = left
            self._kv().kv_put(REFOLD + self._app, FINGERPRINT, sorted(left))
