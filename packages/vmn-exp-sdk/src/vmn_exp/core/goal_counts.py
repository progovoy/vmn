#!/usr/bin/env python3
"""Per-metric counts of the goals an app's runs declare, kept across index
generations (plan 32 follow-up): a run's declaration moving from one value
to another moves its counts, so a generation costs its changed runs, not a
recount (:func:`~vmn_exp.core.metric_schema.goal_counts` is the recount).

:meth:`GoalCounts.shared` hands each snapshot a dict it may keep: an entry's
counts are replaced, never changed in place, and the dict is copied only for
a generation whose goals changed.
"""
from vmn_exp.core.metric_schema import run_goals


class GoalCounts:
    def __init__(self):
        self._counts = {}  # {name: {goal: n}}, each inner dict never mutated
        self._shared = {}

    def move(self, old, new):
        """A run's :func:`~vmn_exp.core.metric_schema.declared_fields` went
        from *old* to *new* (None: none)."""
        before, after = run_goals(old), run_goals(new)
        if before == after:
            return
        for name, goal in before.items():
            self._add(name, goal, -1)
        for name, goal in after.items():
            self._add(name, goal, 1)
        self._shared = None

    def _add(self, name, goal, n):
        counts = dict(self._counts.get(name) or {})
        counts[goal] = counts.get(goal, 0) + n
        if not counts[goal]:
            del counts[goal]
        if counts:
            self._counts[name] = counts
        else:
            self._counts.pop(name, None)

    def shared(self):
        """``{name: {goal: n}}`` as of now; the same dict while unchanged."""
        if self._shared is None:
            self._shared = dict(self._counts)
        return self._shared
