"""Early termination of sweep trials: the median rule and ASHA.

Median: at each step ``s`` the trial logged (from ``min_iter`` on), compare its
best value of the target metric up to ``s`` with the median of the other
trials' best values up to ``s`` — counting only trials that reached ``s``, and
only when at least ``min_trials`` did. Strictly worse than that median at any
of them: stop. Judging every step, not only the latest, keeps the verdict
from hanging on when a polled check lands (past the steps its peers
stopped at, or before they reached its own).

ASHA (asynchronous successive halving, stopping variant): rungs are the steps
``min_iter * eta**k``. The trial is judged at the highest rung it reached, by
its best value up to that rung against the same of every trial that reached
it. With ``n`` such values (its own included) and ``n >= eta``, it is stopped
unless it is among the best ``n // eta`` (a tie keeps it). Fewer than ``eta``:
it keeps running (it never waits for peers).
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


def median_should_stop(own, others, goal, min_iter=1, min_trials=1):
    """Whether the trial with points *own* should stop (see module docstring)."""
    steps = sorted({s for s, _ in own if s >= min_iter})
    if not steps:
        return False
    pick = min if goal == "min" else max
    own_best, peers = _bests(own, pick), [_bests(points, pick) for points in others if points]
    for step in steps:
        reached = _bests_at(peers, step)
        if len(reached) < min_trials:
            continue
        mine, median = _best_until(own_best, step), statistics.median(reached)
        if (mine > median) if goal == "min" else (mine < median):
            return True
    return False


def asha_should_stop(own, others, goal, min_iter, eta):
    """Whether the trial with points *own* should stop under ASHA (see module
    docstring)."""
    rung = _highest_rung(max((s for s, _ in own), default=0), min_iter, eta)
    pick = min if goal == "min" else max
    if rung is None or min(s for s, _ in own) > rung:
        return False
    mine = _best_until(_bests(own, pick), rung)
    values = _bests_at([_bests(points, pick) for points in others if points], rung) + [mine]
    keep = len(values) // eta
    if keep == 0:
        return False
    cut = sorted(values, reverse=goal != "min")[keep - 1]
    return (mine > cut) if goal == "min" else (mine < cut)


def _highest_rung(latest, min_iter, eta):
    if latest < min_iter:
        return None
    rung = min_iter
    while rung * eta <= latest:
        rung *= eta
    return rung


def _bests(points, pick):
    """``(steps, best value up to each)`` of *points*, in step order."""
    ordered = sorted(points)
    return [s for s, _ in ordered], list(itertools.accumulate((v for _, v in ordered), pick))


def _bests_at(peers, step):
    """The best value up to *step* of each of *peers* that reached it."""
    return [_best_until(peer, step) for peer in peers if peer[0][0] <= step <= peer[0][-1]]


def _best_until(bests, step):
    steps, values = bests
    return values[bisect.bisect_right(steps, step) - 1]


class _Stopper:
    """The spec's early-termination rule for one running trial, checked at
    most every ``check_interval_sec``; ``due(now)`` says when a check should
    run (the first one an interval after the trial started: nothing is logged
    before)."""

    def __init__(self, spec):
        self.goal = spec["metric"]["goal"]
        self.rule = spec["early_terminate"]
        self._next = None

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


class MedianStopper(_Stopper):
    def should_stop(self, own, others):
        return median_should_stop(
            own, others, self.goal,
            min_iter=self.rule["min_iter"], min_trials=self.rule["min_trials"],
        )


class AshaStopper(_Stopper):
    def should_stop(self, own, others):
        return asha_should_stop(
            own, others, self.goal, min_iter=self.rule["min_iter"], eta=self.rule["eta"])


def stopper_for(spec):
    """The stopper for the rule ``spec["early_terminate"]["type"]`` names."""
    rules = {"median": MedianStopper, "asha": AshaStopper}
    return rules[spec["early_terminate"]["type"]](spec)
