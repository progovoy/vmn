#!/usr/bin/env python3
"""The fold's step restarts: per metric, whether its last write's step is
below its highest step — its steps went back without a rewind (a resumed
writer restarting its counter) and stayed below, so the row's latest value
is not the value at the highest step. Index rows mark it.

The fold keeps ``steps[name] = [highest step, last write's step]`` of each
stepped metric: a max, and the step of the point holding the greatest fold
key (the one ``metrics`` keeps), so writers' chunks fold in any order to
what the merged log folds to. A chain — a log entry's point, a block
header's (``.vmx`` footer's, writer sums') key — gives its highest step
(its ``r[0]`` where it went back, else its last point's) and its last point.
A step-less last write leaves the mark off; a rewind hides points before
they fold. (The run page marks the first write that went back instead,
:class:`~vmn_exp.core.step_restart.StepRestarts`.) Pure.
"""
from vmn_exp.core.step_restart import ended_below, restart_view


def track_steps(fold, name, top, last, last_key):
    """Fold a chain of *name*'s points whose highest step is *top* and whose
    last write, at fold key *last_key*, is at step *last* (either None:
    step-less). Call it before the chain's values fold in."""
    current = fold["metrics"].get(name)
    steps = fold.setdefault("steps", {})
    held = steps.get(name) or [None, None]
    if top is not None and (held[0] is None or top > held[0]):
        held[0] = top
    if current is None or tuple(last_key) >= tuple(current[1:]):
        held[1] = last
    if held[0] is not None:
        steps[name] = held


def chain_top(entry):
    """A header entry's highest step (see the module)."""
    return entry["r"][0] if "r" in entry else entry["last"][1]


def step_restarts(fold):
    """``{metric: {"from": highest step, "to": last write's step}}``."""
    found = ((name, ended_below(*held)) for name, held in (fold.get("steps") or {}).items())
    return {name: restart_view(r) for name, r in found if r}
