#!/usr/bin/env python3
"""The one metric writer (plan 12 §4.1): per-key array buffers, one block of
``metrics/<writer>.vms`` per :meth:`MetricWriter.flush`.

A key is step-less when logged without a step. A key this writer also logs
with a step keeps its stepped points under its name and puts its step-less
ones under :func:`stepless_twin`, which the reader merges back (§3.1).
Values arrive coerced (:mod:`vmn_exp.core.values`); the writer only records.
"""
import threading
import time
from array import array

from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns

_TWIN_SUFFIX = "@nostep"


def stepless_twin(key):
    """The internal name of *key*'s step-less points when it also has steps."""
    return key + _TWIN_SUFFIX


class _Buffer:
    def __init__(self):
        self.steps, self.ts, self.values = array("q"), array("q"), array("d")

    def add(self, step, ts_us, value):
        if step is not None:
            self.steps.append(step)
        self.ts.append(ts_us)
        self.values.append(value)

    def columns(self, has_step):
        return Columns(self.steps if has_step else None, self.ts, self.values)


class MetricWriter:
    def __init__(self, storage, app_name, verstr, writer_id, clock=time.time):
        self._storage, self._clock = storage, clock
        self._target = (app_name, verstr, writer_id)
        self._stepped, self._stepless = {}, {}
        self._has_steps = set()  # keys this writer ever logged with a step
        self._lock = threading.Lock()

    def add(self, key, value, step=None, ts=None):
        """Buffer one point; *ts* in epoch seconds (default: now)."""
        ts_us = int((self._clock() if ts is None else ts) * 1_000_000)
        with self._lock:
            target = self._stepless if step is None else self._stepped
            target.setdefault(key, _Buffer()).add(
                None if step is None else int(step), ts_us, float(value))

    def flush(self):
        """Append the buffered points as one block; True when nothing was
        pending or the append succeeded. A failed append keeps them."""
        with self._lock:
            keys = self._block_keys()
            if not keys:
                return True
            self._storage.append_metric_block(*self._target, encode_block(keys))
            self._has_steps.update(self._stepped)
            self._stepped, self._stepless = {}, {}
            return True

    def _block_keys(self):
        keys = {k: b.columns(True) for k, b in self._stepped.items()}
        for key, buf in self._stepless.items():
            split = key in self._stepped or key in self._has_steps
            keys[stepless_twin(key) if split else key] = buf.columns(False)
        return keys
