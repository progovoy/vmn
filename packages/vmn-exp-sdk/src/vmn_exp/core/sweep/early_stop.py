"""Median stopping: end a trial whose best-so-far trails its peers' median.

At the trial's latest step ``s`` (once ``s >= min_iter``), compare its best
value of the target metric up to ``s`` with the median of the other trials'
best values up to ``s`` — counting only trials that reached ``s``, and only when
at least ``min_trials`` did. Strictly worse than that median: stop.
"""
import statistics


def step_points(points):
    """``[(step, value)]`` of a metric series; a point without a step is
    numbered by its position in the log (1-based)."""
    return [
        (p["step"] if p.get("step") is not None else i, p["value"])
        for i, p in enumerate(points, start=1)
        if isinstance(p.get("value"), (int, float))
    ]


def median_should_stop(own, others, goal, min_iter=1, min_trials=1):
    """Whether the trial with points *own* should stop (see module docstring)."""
    if not own:
        return False
    step = max(s for s, _ in own)
    if step < min_iter:
        return False
    peers = [_best_until(points, step, goal) for points in others
             if points and max(s for s, _ in points) >= step]
    if len(peers) < min_trials:
        return False
    own_best, median = _best_until(own, step, goal), statistics.median(peers)
    return own_best > median if goal == "min" else own_best < median


def _best_until(points, step, goal):
    values = [v for s, v in points if s <= step]
    return min(values) if goal == "min" else max(values)


class MedianStopper:
    """The spec's median rule for one running trial, checked at most every
    ``check_interval_sec``; ``due(now)`` says when a check should run (the
    first one an interval after the trial started: nothing is logged before)."""

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

    def should_stop(self, own, others):
        return median_should_stop(
            own, others, self.goal,
            min_iter=self.rule["min_iter"], min_trials=self.rule["min_trials"],
        )
