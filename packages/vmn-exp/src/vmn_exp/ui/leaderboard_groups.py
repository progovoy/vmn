#!/usr/bin/env python3
"""The grouped leaderboard (plan 22 K1/K2): the filtered rows of one
snapshot partitioned by a group field, rows within a group and groups among
themselves ordered by the sort.

Rows keep the flat board's order (:func:`~vmn_exp.ui.leaderboard_live.order_key`).
When the sort ranks by a metric, groups order by their aggregate (*agg*) of
it — missing ones after, ties by their first row — else by their first row;
the ``(none)`` group always comes last. Grouped by a link, that group is
``loose``: the runs heading a group are left out of it
(:mod:`~vmn_exp.ui.leaderboard_group_loose`). A count sort orders groups by that
count (:class:`~vmn_exp.ui.leaderboard_group_spec.GroupSpec`).

Like :class:`~vmn_exp.ui.leaderboard_cache._Static`, a :class:`Grouping`
covers the rows no time bucket changes: :meth:`Grouping.build` partitions a
static order once, :meth:`Grouping.advanced` moves it to a new generation by
the rows that left and joined (only their groups are placed again, their
:class:`~vmn_exp.ui.leaderboard_group_summary.Summary` moved by those rows),
and :meth:`Grouping.merged` places a bucket's changed rows into it. Rows
handed out are shared: callers must treat them as read-only.
"""
from vmn_exp.ui.leaderboard_delta import splice
from vmn_exp.ui.leaderboard_group_clause import clause
from vmn_exp.ui.leaderboard_group_fields import (
    NONE,
    RERUN_OF,
    TARGET_LINKS,
    UnknownGroup,
    escaped_key,
    key_text,
    label,
    target_payload,
)
from vmn_exp.ui.leaderboard_group_loose import Loose
from vmn_exp.ui.leaderboard_group_summary import Summary
from vmn_exp.ui.leaderboard_live import MergedRows, _bisect


def _partition(rows, key_of):
    members = {}
    for row in rows:
        members.setdefault(key_of(row), []).append(row)
    return members


class Grouping:
    """Groups of one snapshot's filtered rows: ``members`` ``{key: rows in
    order}``, ``summaries`` ``{key: Summary}``, ``order`` the keys but
    ``(none)`` in group order."""

    def __init__(self, base, spec, members, summaries, key, ranked, with_metric, live=None):
        self.token = base.token
        self.base, self.spec = base, spec
        self.members, self.summaries = members, summaries
        self.key, self.ranked = key, ranked
        self.with_metric = with_metric  # rows carrying the sort metric
        self.live = live  # {storage index: row} of a bucket's view, else None
        self._changed = set(base.patch.changed)
        self._okeys, self.order = {}, []
        self._total = self._running = None
        self._aggregates = {}  # memo: {group: aggregates payload}
        self._loose_rows = None  # memo: a link grouping's Loose
        self._job_groups = None  # memo: (job summaries, JobGroups) of a Jobs view

    @classmethod
    def build(cls, base, spec, static):
        """From a static order (:class:`~vmn_exp.ui.leaderboard_cache._Static`
        of the same filters): O(N)."""
        key, ranked = spec.row_key(base.position, static.has_metric)
        return cls._of_sorted(base, spec, static.sorted, key, ranked, static.with_metric, None)

    @classmethod
    def of_rows(cls, base, spec, rows, live=None):
        """From any filtered *rows*: sorted here, O(N log N)."""
        with_metric = spec.carrying(rows)
        key, ranked = spec.row_key(base.position, bool(with_metric))
        return cls._of_sorted(base, spec, sorted(rows, key=key), key, ranked, with_metric, live)

    @classmethod
    def _of_sorted(cls, base, spec, rows, key, ranked, with_metric, live):
        members = _partition(rows, spec.key_of)
        summaries = {group: Summary.of(kept) for group, kept in members.items()}
        grouping = cls(base, spec, members, summaries, key, ranked, with_metric, live)
        return grouping._ordered(members, None)

    @property
    def has_metric(self):
        return bool(self.with_metric)

    def advanced(self, base, left, joined):
        """Moved to *base*'s static rows; None when whether any row carries
        the sort metric flips (the row order changes shape)."""
        spec = self.spec
        members, summaries = dict(self.members), dict(self.summaries)
        dirty, dropped = self._dropped(members, summaries, left)
        joined_rows = spec.filtered(base.snapshot, joined)
        with_metric = self.with_metric - spec.carrying(dropped) + spec.carrying(joined_rows)
        if bool(with_metric) != self.has_metric:
            return None
        key, ranked = spec.row_key(base.position, self.has_metric)
        for group, rows in _partition(joined_rows, spec.key_of).items():
            members[group] = splice(members.get(group, []), [], key, rows, key)
            summaries[group] = self._owned(summaries, group, dirty).add(rows)
            dirty.add(group)
        if spec.group == RERUN_OF:
            dirty.update(escaped_key(row["verstr"]) for row in list(left) + list(joined))
        moved = Grouping(base, spec, members, summaries, key, ranked, with_metric)
        return moved._from(self, dirty)

    @staticmethod
    def _owned(summaries, group, dirty):
        """*group*'s summary, copied once per move before it is written."""
        summary = summaries.get(group)
        if summary is None:
            return Summary()
        return summary if group in dirty else summary.copy()

    def _dropped(self, members, summaries, left):
        """``(groups, rows)``: the groups *left* rows were in, and those rows,
        taken out of *members* and *summaries*."""
        by_group = {}
        for row in left:
            by_group.setdefault(self.spec.key_of(row), set()).add(id(row))
        dirty, every = set(), []
        for group, ids in by_group.items():
            kept, dropped = [], []
            for row in members.get(group, ()):
                (dropped if id(row) in ids else kept).append(row)
            if dropped:
                members[group] = kept
                summaries[group] = summaries[group].copy().remove(dropped)
                dirty.add(group)
                every.extend(dropped)
        return dirty, every

    def merged(self, base, bucket):
        """This grouping with the bucket's filtered changed rows placed in."""
        spec, changed = self.spec, base.changed_at(bucket)
        live = dict(zip(base.patch.changed, changed))
        rows = spec.filtered(base.snapshot, changed)
        with_metric = self.with_metric + spec.carrying(rows)
        key, ranked = spec.row_key(base.position, bool(with_metric))
        if ranked != self.ranked:  # only live rows carry the metric
            every = [row for group in self.members.values() for row in group]
            return Grouping.of_rows(base, spec, every + rows, live)
        members, summaries = dict(self.members), dict(self.summaries)
        dirty = set()
        for group, add in _partition(sorted(rows, key=key), spec.key_of).items():
            members[group] = MergedRows(self.members.get(group, []), add, key)
            summaries[group] = self._owned(summaries, group, ()).add(add)
            dirty.add(group)
        if spec.group == RERUN_OF:
            dirty.update(escaped_key(row["verstr"]) for row in changed)
        view = Grouping(base, spec, members, summaries, key, ranked, with_metric, live)
        return view._from(self, dirty)

    # -- group order ------------------------------------------------------
    def _from(self, prev, dirty):
        """*prev*'s group order with the *dirty* groups placed again."""
        for group in [g for g in dirty if g in self.members and not len(self.members[g])]:
            del self.members[group]
            del self.summaries[group]
        self._okeys = dict(prev._okeys)
        return self._ordered(dirty, [g for g in prev.order if g not in dirty])

    def _ordered(self, dirty, kept):
        """Group keys and order: the *dirty* groups' anew; *kept* (None:
        every group is dirty) stays in place."""
        placed = [g for g in dirty if g in self.members and g != NONE]
        for group in dirty:
            self._okeys.pop(group, None)
        for group in placed:
            self._okeys[group] = self._group_key(group)
        okey = self._okeys.__getitem__
        if kept is None:
            self.order = sorted(placed, key=okey)
            return self
        for group in sorted(placed, key=okey):
            kept.insert(_bisect(kept, okey(group), okey), group)
        self.order = kept
        return self

    def _group_key(self, group):
        first = self.key(self.members[group][:1][0])
        if not self.ranked:
            key = (first,)
        else:
            value = self.spec.value(self._summary(group))
            key = (1, first) if value is None else (0, value, first)
        count = self.spec.count(self.summaries[group])
        return key if count is None else (count,) + key

    # -- what a group says -------------------------------------------------
    def row_of(self, verstr):
        """*verstr*'s row in this view (unfiltered), or None when not indexed."""
        i = self.base.position.get(verstr)
        if i is None:
            return None
        return (self.live or {}).get(i, self.base.rows[i])

    def _summary(self, group):
        """*group*'s summary, a rerun group's original counted when it passes
        the filters (G3: the original's value is part of the result)."""
        summary = self._own(group)
        if self.spec.group != RERUN_OF or group == NONE:
            return summary
        i = self.base.position.get(key_text(group))
        if i is None or (self.live is None and i in self._changed):
            return summary
        original = self.row_of(key_text(group))
        return summary.with_rows(self.spec.filtered(self.base.snapshot, [original]))

    def _aggregates_of(self, group):
        found = self._aggregates.get(group)
        if found is None:
            found = self._aggregates[group] = self._summary(group).aggregates(self.spec.schema)
        return found

    def _is_loose(self, key):
        return key == NONE and self.spec.group in TARGET_LINKS

    def _own(self, key):
        """*key*'s summary of its own rows."""
        return self._loose().summary if self._is_loose(key) else self.summaries[key]

    def _loose(self):
        if self._loose_rows is None:
            self._loose_rows = Loose(self)
        return self._loose_rows

    def has(self, key):
        return self.size(key) > 0

    def keys(self):
        return self.order + ([NONE] if self.has(NONE) else [])

    @property
    def total(self):
        if self._total is None:
            self._total = sum(s.size for s in self.summaries.values())
        return self._total

    @property
    def running(self):
        """Running rows across every group."""
        if self._running is None:
            self._running = sum(s.statuses.get("running", 0) for s in self.summaries.values())
        return self._running

    def size(self, key):
        if self._is_loose(key) and NONE in self.members:
            return self._loose().size
        return len(self.members.get(key, ()))

    def _rows(self, key, offset, limit):
        if self._is_loose(key):
            return self._loose().page(offset, limit)
        return list(self.members[key][offset:offset + limit])

    def group(self, key, offset, limit, unfiltered=None):
        """One group's payload, its rows paged; ``rows_unfiltered`` is the
        group's size in *unfiltered* (the same grouping without the filters)."""
        linked = self.spec.group in TARGET_LINKS and key != NONE
        target = self.row_of(key_text(key)) if linked else None
        first = self._rows(key, 0, 1)
        return {"key": key, "label": label(self.spec.group, key, target is not None),
                "target": target_payload(target) if target else None,
                "loose": self._is_loose(key),
                "counts": self._own(key).counts(),
                "aggregates": self._aggregates_of(key),
                "rows": self._rows(key, offset, limit), "rows_total": self.size(key),
                "rows_unfiltered": (unfiltered or self).size(key),
                "clause": clause(self.spec.group, key, first[0] if first else {},
                                 self._is_loose(key))}


def groups_payload(grouping, offset=0, limit=None, rows_per_group=10, group_key=None,
                   unfiltered=None, extra=None):
    """K1's answer: a page of groups, or with *group_key* one group's rows
    paged by *offset*/*limit* (:class:`UnknownGroup` when there is none).
    *unfiltered* (default: *grouping*) sizes each group before the filters;
    *extra* (key -> dict) adds fields to each group."""
    limit = 50 if limit is None else limit

    def group(key, start, count):
        out = grouping.group(key, start, count, unfiltered)
        return dict(out, **extra(key)) if extra else out

    if group_key is not None:
        if not grouping.has(group_key):
            raise UnknownGroup(f"no group {group_key!r}")
        return group(group_key, offset, limit)
    keys = grouping.keys()
    return {"groups": [group(k, 0, rows_per_group) for k in keys[offset:offset + limit]],
            "total_groups": len(keys), "total_rows": grouping.total,
            "running": grouping.running, "aggregate": grouping.spec.agg}
