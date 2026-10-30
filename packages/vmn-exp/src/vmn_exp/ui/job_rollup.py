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

Archived rows are left out, as the board leaves them out by default, and
an archived job takes its whole subtree out of the jobs above it (its own
rollup still reads its subtree): :class:`JobTree`'s one membership rule,
which the attention counts follow too (:meth:`JobTree.counted_in`,
:meth:`JobTree.top_counted`).
"""
from functools import cached_property

from vmn_exp.core.tree import counted_chain, subtree_verstrs
from vmn_exp.ui.leaderboard_facets import visible


def _parent(row):
    parent = row.get("parent")
    return parent if parent and parent != row["verstr"] else None


def _tallies(rows, spec):
    """``{parent: spec.tally()}`` of the visible *rows*."""
    tallies = {}
    for row in visible(rows, False):
        parent = _parent(row)
        if parent:
            if parent not in tallies:
                tallies[parent] = spec.tally()
            tallies[parent].add(row, spec)
    return tallies


def _tally_of(rows, spec):
    tally = spec.tally()
    for row in rows:
        tally.add(row, spec)
    return tally


def _static_rows(base, changed):
    return [row for i, row in enumerate(base.rows) if i not in changed]


def _static_children(base, parent, changed):
    at = (base.position[kid] for kid in base.children_of.get(parent, ()))
    return visible([base.rows[i] for i in at if i not in changed], False)


class StaticRollups:
    """``{parent: tally}`` of one base's static rows, for one *spec*: a
    schema's :class:`~vmn_exp.ui.job_tally.RollupSpec` (its tallies are
    :class:`~vmn_exp.ui.job_tally.Tally`) or a
    :class:`~vmn_exp.ui.job_split.SplitSpec` (per-value tallies)."""

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
        # Joined first: a row replaced by an equal one keeps the extremes it holds.
        for rows, by in ((joined, 1), (left, -1)):
            for row in visible(rows, False):
                parent = _parent(row)
                if not parent:
                    continue
                if parent not in owned:
                    owned.add(parent)
                    tallies[parent] = tallies[parent].copy() if parent in tallies else self.spec.tally()
                if tallies[parent].add(row, self.spec, by):
                    unknown.add(parent)
        changed = set(base.patch.changed) if unknown else ()
        for parent in unknown:
            children = _static_children(base, parent, changed)
            tallies[parent] = _tally_of(children, self.spec)
        for parent in owned:
            if tallies[parent].empty():
                del tallies[parent]
        return StaticRollups(base.token, self.spec, tallies)


def overlay(base, bucket, spec):
    """``{parent: tally}`` of *base*'s changed rows as of *bucket*."""
    return _tallies(base.changed_at(bucket), spec)


class JobTree:
    """One base's jobs (present runs with children), the jobs right under
    each, and the top-level ones (under no job)."""

    def __init__(self, base):
        self._base = base
        self.jobs = {v for v, kids in base.children_of.items() if kids and v in base.position}
        self.nested = {job: [kid for kid in base.children_of[job] if kid in self.jobs]
                       for job in self.jobs}
        self._parent = {kid: job for job, kids in self.nested.items() for kid in kids}
        self.top = [job for job in self.jobs if job not in self._parent]
        self.archived = {job for job in self.jobs if base.rows[base.position[job]].get("archived")}
        self._counted = {job: [kid for kid in kids if kid not in self.archived]
                         for job, kids in self.nested.items()}

    def peers(self, job):
        """The jobs beside *job*: under its parent job, else the top-level ones."""
        parent = self._parent.get(job)
        return self.top if parent is None else self.nested[parent]

    def subtree_jobs(self, job):
        """*job* and every job below it but under no archived one (cycle-safe)."""
        return subtree_verstrs(job, self._counted)

    def counted_in(self, verstr):
        """*verstr* and the jobs it counts in, nearest first: up its parent
        chain to its nearest archived job (whose own rollup reads its
        subtree; the jobs above it do not)."""
        if verstr in self.jobs:
            return [verstr, *counted_chain(verstr, self._parent, self.archived.__contains__)]
        parent = self._job_above(verstr)
        return [verstr, *self.counted_in(parent)] if parent else [verstr]

    def top_counted(self, verstr):
        """The last of :meth:`counted_in` *verstr*: the top-most run it counts in."""
        job = verstr if verstr in self.jobs else self._job_above(verstr)
        return self._top_counted[job] if job else verstr

    @cached_property
    def _top_counted(self):
        return {job: self.counted_in(job)[-1] for job in self.jobs}

    def _job_above(self, verstr):
        """*verstr*'s parent when it is a job, else None."""
        at = self._base.position.get(verstr)
        parent = _parent(self._base.rows[at]) if at is not None else None
        return parent if parent in self.jobs else None
