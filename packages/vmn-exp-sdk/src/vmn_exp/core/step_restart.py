#!/usr/bin/env python3
"""A metric whose steps went back: a write at a step not past every earlier
write's, e.g. a resumed writer that restarted its step counter.

Read from a series in write order. A rewind is not a restart: the points it
hides are gone from the series already (:mod:`~vmn_exp.core.rewind`), and a
run continues past the rewound step. Step-less points never count. Pure.
"""


class StepRestarts:
    """Per metric, the first write whose step went back, fed point lists as
    the series grows: ``found[metric] = {"write": n, "from": s, "to": t}``
    (*n* counts the metric's points from 1; *s* the highest earlier step)."""

    def __init__(self):
        self.found = {}
        self._top = {}  # metric -> highest step so far
        self._written = {}  # metric -> points seen

    def add(self, key, points):
        if key in self.found:
            return
        top, written = self._top.get(key), self._written.get(key, 0)
        for point in points:
            written += 1
            step = point.get("step")
            if step is None:
                continue
            if top is not None and step <= top:
                self.found[key] = {"write": written, "from": top, "to": step}
                return
            top = step
        self._top[key], self._written[key] = top, written
