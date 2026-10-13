#!/usr/bin/env python3
"""Per-job rollups over each job's whole subtree (plan 23 S1).

A job is any run with children. Each row's contribution goes to one
:class:`~vmn_exp.ui.job_tally.Tally`, its parent's, and a job's rollup
reads its own tally plus those of the jobs nested under it — so re-linking
a job moves its subtree with it at no cost, and a row is always taken back
out of the tally it went into (its ``parent`` field, on the row object the
delta hands back).

As :class:`~vmn_exp.ui.leaderboard_cache._Static` keeps its orders, the
tallies cover the rows no time bucket changes and move across generations
by the cache's deltas (:meth:`StaticRollups.advanced`): the left rows out,
the joined ones in, each tally copied on its first write. A removal that
takes away a tally's extreme (min, max, best, first start, last end)
recomputes that one tally from its parent's static children, at most once a
generation. The live rows (and their ancestors) are an overlay of tallies
built per time bucket (:func:`overlay`).

Archived rows are left out, as the board leaves them out by default.
"""
from vmn_exp.ui.job_tally import Tally
from vmn_exp.ui.leaderboard_tree import parent_in


def _parent(row):
    parent = row.get("parent")
    return parent if parent and parent != row["verstr"] else None


def _tallies(rows, spec):
    """``{parent: Tally}`` of the visible *rows*."""
    tallies = {}
    for row in rows:
        parent = _parent(row)
        if parent and not row.get("archived"):
            tallies.setdefault(parent, Tally()).add(row, spec)
    return tallies


def _static_rows(base, changed):
    return [row for i, row in enumerate(base.rows) if i not in changed]


def _static_children(base, parent, changed):
    rows = (base.rows[base.position[kid]] for kid in base.children_of.get(parent, ()))
    return [row for row in rows if base.position[row["verstr"]] not in changed]


class StaticRollups:
    """``{parent: Tally}`` of one base's static rows, for one schema's spec."""

    def __init__(self, token, spec, tallies):
        self.token = token  # of the base these tallies were built or moved for
        self.spec = spec
        self.tallies = tallies

    @classmethod
    def build(cls, base, spec):
        """From scratch: O(N)."""
        return cls(base.token, spec, _tallies(_static_rows(base, set(base.patch.changed)), spec))

    def advanced(self, base, left, joined):
        """These tallies moved to *base*: the *left* rows out, the *joined* in."""
        tallies, owned, unknown = dict(self.tallies), set(), set()
        for rows, by in ((left, -1), (joined, 1)):
            for row in rows:
                parent = _parent(row)
                if not parent or row.get("archived"):
                    continue
                if parent not in owned:
                    owned.add(parent)
                    tallies[parent] = tallies[parent].copy() if parent in tallies else Tally()
                if tallies[parent].add(row, self.spec, by):
                    unknown.add(parent)
        changed = set(base.patch.changed) if unknown else ()
        for parent in unknown:
            children = _static_children(base, parent, changed)
            tallies[parent] = _tallies(children, self.spec).get(parent, Tally())
        for parent in owned:
            if not tallies[parent].counts:
                del tallies[parent]
        return StaticRollups(base.token, self.spec, tallies)


def overlay(base, bucket, spec):
    """``{parent: Tally}`` of *base*'s changed rows as of *bucket*."""
    return _tallies(base.changed_at(bucket), spec)


class JobTree:
    """One base's jobs (present runs with children) and the jobs right under each."""

    def __init__(self, base):
        self.jobs = {v for v, kids in base.children_of.items() if kids and v in base.position}
        self.nested = {}
        for job in self.jobs:
            parent = parent_in(base.snapshot.edges, job)
            if parent in self.jobs:
                self.nested.setdefault(parent, []).append(job)

    def subtree_jobs(self, job):
        """*job* and every job below it (cycle-safe)."""
        out, stack, seen = [], [job], set()
        while stack:
            verstr = stack.pop()
            if verstr not in seen:
                seen.add(verstr)
                out.append(verstr)
                stack.extend(self.nested.get(verstr, ()))
        return out
