"""Median stopping: end a trial whose best-so-far trails its peers' median.

At the trial's latest step ``s`` (once ``s >= min_iter``), compare its best
value of the target metric up to ``s`` with the median of the other trials'
best values up to ``s`` — counting only trials that reached ``s``, and only when
at least ``min_trials`` did. Strictly worse than that median: stop.

A polled check judges every step logged since the previous check, not only
the latest: a slow poll that lands past the steps its peers reached must
not let the trial off.
"""
import bisect
import itertools
import statistics

from vmn_exp.core.values import is_finite_number


def step_points(points):
    """``[(step, value)]`` of a metric series; a point without a step is
    numbered by its position in the log (1-based). Only finite values count."""
    return [
        (p["step"] if p.get("step") is not None else i, p["value"])
        for i, p in enumerate(points, start=1)
        if is_finite_number(p.get("value"))
    ]


def median_should_stop(own, others, goal, min_iter=1, min_trials=1, after=None):
    """Whether the trial with points *own* should stop (see module docstring):
    judged at its latest step or, given *after*, at each of its steps past it."""
    steps = sorted({s for s, _ in own if s >= min_iter})
    steps = steps[-1:] if after is None else [s for s in steps if s > after]
    if not steps:
        return False
    pick = min if goal == "min" else max
    own_best, peers = _bests(own, pick), [_bests(points, pick) for points in others if points]
    for step in steps:
        reached = [_best_until(peer, step) for peer in peers if peer[0][0] <= step <= peer[0][-1]]
        if len(reached) < min_trials:
            continue
        mine, median = _best_until(own_best, step), statistics.median(reached)
        if (mine > median) if goal == "min" else (mine < median):
            return True
    return False


def _bests(points, pick):
    """``(steps, best value up to each)`` of *points*, in step order."""
    ordered = sorted(points)
    return [s for s, _ in ordered], list(itertools.accumulate((v for _, v in ordered), pick))


def _best_until(bests, step):
    steps, values = bests
    return values[bisect.bisect_right(steps, step) - 1]


class MedianStopper:
    """The spec's median rule for one running trial, checked at most every
    ``check_interval_sec``; ``due(now)`` says when a check should run (the
    first one an interval after the trial started: nothing is logged before)."""

    def __init__(self, spec):
        self.goal = spec["metric"]["goal"]
        self.rule = spec["early_terminate"]
        self._next = None
        self._judged = float("-inf")  # the latest step a check judged

    def due(self, now):
        if self._next is None:
            self._next = now + self.rule["check_interval_sec"]
        if now < self._next:
            return False
        self._next = now + self.rule["check_interval_sec"]
        return True

    def past_min_iter(self, own):
        """Whether the trial with points *own* is far enough to be judged."""
        return bool(own) and max(s for s, _ in own) >= self.rule["min_iter"]

    def should_stop(self, own, others):
        """Whether any step of *own* logged since the last check trails."""
        stop = median_should_stop(
            own, others, self.goal, min_iter=self.rule["min_iter"],
            min_trials=self.rule["min_trials"], after=self._judged,
        )
        self._judged = max([self._judged] + [s for s, _ in own])
        return stop
