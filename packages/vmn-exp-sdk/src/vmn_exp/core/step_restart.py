#!/usr/bin/env python3
"""A metric whose steps went back: a write at a step not past every earlier
write's, e.g. a resumed writer that restarted its step counter.

Read from a series in write order. A rewind is not a restart: the points it
hides are gone from the series already (:mod:`~vmn_exp.core.rewind`), and a
run continues past the rewound step. Step-less points never count. Pure.
"""


def _first_back(steps, top=None):
    """``(index, top)``: the first of *steps* not past *top* and every earlier
    one (index None when none), *top* the highest step before it."""
    for i, step in enumerate(steps):
        if step is None:
            continue
        if top is not None and step <= top:
            return i, top
        top = step
    return None, top


def restart_point(steps):
    """``[from, to]`` of the first of *steps* (in write order; None: a
    step-less key) not past every earlier one, *from* the highest earlier
    step; None when none goes back."""
    if steps is None:
        return None
    steps = list(steps)
    i, top = _first_back(steps)
    return None if i is None else [top, steps[i]]


def with_restart(summary, restart):
    """*summary* with ``r`` = *restart* when there is one (else left out)."""
    if restart is not None:
        summary["r"] = restart
    return summary


def restart_view(restart):
    """A ``[from, to]`` restart as rows and answers carry it."""
    return {"from": restart[0], "to": restart[1]}


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
        steps = [point.get("step") for point in points]
        written = self._written.get(key, 0)
        i, top = _first_back(steps, self._top.get(key))
        if i is not None:
            self.found[key] = {"write": written + i + 1, **restart_view([top, steps[i]])}
            return
        self._top[key], self._written[key] = top, written + len(steps)
