#!/usr/bin/env python3
"""A metric whose steps went back: a write at a step not past every earlier
write's, e.g. a resumed writer that restarted its step counter.

Read from a series in write order. A rewind is not a restart: the points it
hides are gone from the series already (:mod:`~vmn_exp.core.rewind`), and a
run continues past the rewound step. Step-less points never count. The run
page marks the first write that went back (:class:`StepRestarts`); rows and
file summaries mark a last write below the highest step, which folds in any
order (:func:`restart_point`). Pure.
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
    """``[top, last]`` of *steps* (in write order; None: a step-less key)
    whose last step is below their highest: they went back and stayed below
    it, so the last write is not the value at the highest step. None
    otherwise. Unlike :class:`StepRestarts` it depends on no order but the
    last write's, so writers' chunks combine in any order (max and latest)."""
    top = last = None
    for step in steps or ():
        if step is None:
            continue
        last = step
        if top is None or step > top:
            top = step
    return ended_below(top, last)


def ended_below(top, last):
    """``[top, last]`` when the *last* write's step is below the *top* step."""
    return [top, last] if top is not None and last is not None and last < top else None


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
