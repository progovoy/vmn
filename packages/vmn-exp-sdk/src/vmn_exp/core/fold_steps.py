#!/usr/bin/env python3
"""The fold's step restarts: per metric, whether its steps went back without
a rewind (:mod:`~vmn_exp.core.step_restart`), so index rows can mark it.

Points fold in *chains*: a log entry's point, or a block header's (``.vmx``
footer's, writer sums') key, whose steps rise in write order unless it says
where they went back (``r``). The fold keeps a stepped metric's
``steps[name] = [lowest, highest]`` while its chains rise, and on the first
that goes back moves it to ``restarts[name] = [from, to]``. A chain is
ordered against what the metric folded so far by fold key — the first and
last keys the fold holds for it (``firsts``, ``metrics``) — so writers'
chunks may fold in any order: a chain after them must start past the
highest step, one before them end below the lowest, and one among them
(two writers interleaving the metric) goes back. Step-less points never
count; a rewind hides points before they fold. Pure.
"""


def track_steps(fold, name, first, last, restart=None):
    """Fold a chain of *name*'s points whose write-ordered ends are *first*
    and *last* (``(step, fold key)``), rising unless *restart* (``[from,
    to]``). Call it before the chain's values fold in."""
    restarts = fold.get("restarts")
    if first[0] is None or (restarts and name in restarts):
        return
    steps = fold.setdefault("steps", {})
    held = steps.get(name)
    if restart is None and held is not None:
        restart, merged = joined(held, _bounds(fold, name), first, last)
    else:
        merged = [first[0], last[0]]
    if restart is None:
        steps[name] = merged
        return
    steps.pop(name, None)
    fold.setdefault("restarts", {})[name] = list(restart)


def _bounds(fold, name):
    """The first and last fold keys of *name*'s folded points."""
    last = tuple(fold["metrics"][name][1:])
    firsts = fold.get("firsts") or {}
    return (tuple(firsts[name][1:]) if name in firsts else last), last


def joined(held, bounds, first, last):
    """``(restart, merged [lowest, highest])`` of a chain from *first* to
    *last* joining the rising *held* steps folded between *bounds*."""
    (low, high), (lo_key, hi_key) = held, bounds
    if tuple(first[1]) > hi_key:
        return ([high, first[0]] if first[0] <= high else None), [low, last[0]]
    if tuple(last[1]) < lo_key:
        return ([last[0], low] if low <= last[0] else None), [first[0], high]
    return ([high, first[0]] if first[0] <= high else [last[0], low]), None


def step_restarts(fold):
    """``{metric: {"from", "to"}}`` of the restarts *fold* found."""
    return {name: {"from": r[0], "to": r[1]} for name, r in (fold.get("restarts") or {}).items()}
