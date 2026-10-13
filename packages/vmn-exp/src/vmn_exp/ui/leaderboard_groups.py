#!/usr/bin/env python3
"""The grouped leaderboard (plan 22 K1/K2): the filtered rows of one
snapshot partitioned by a group field, rows within a group and groups among
themselves ordered by the sort.

Rows keep the flat board's order (:func:`~vmn_exp.ui.leaderboard_live.order_key`).
When the sort ranks by a metric, groups order by their aggregate (*agg*) of
it — missing ones after, ties by their first row — else by their first row;
the ``(none)`` group always comes last.

Like :class:`~vmn_exp.ui.leaderboard_cache._Static`, a :class:`Grouping`
covers the rows no time bucket changes: :meth:`Grouping.build` partitions a
static order once, :meth:`Grouping.advanced` moves it to a new generation by
the rows that left and joined (only their groups are placed again, their
:class:`~vmn_exp.ui.leaderboard_group_summary.Summary` moved by those rows),
and :meth:`Grouping.merged` places a bucket's changed rows into it. Rows
handed out are shared: callers must treat them as read-only.
"""
from vmn_exp.core.log import primary_metric, sort_descending
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.ui.leaderboard_delta import splice
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.leaderboard_group_fields import (
    NONE,
    RERUN_OF,
    TARGET_LINKS,
    UnknownGroup,
    check_aggregate,
    check_group,
    key_of,
    label,
    target_payload,
)
from vmn_exp.ui.leaderboard_group_summary import Summary
from vmn_exp.ui.leaderboard_live import MergedRows, _bisect, order_key
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING
from vmn_exp.ui.readers.experiments import apply_filters


class GroupSpec:
    """One grouping's field, aggregate, sort and filters."""

    def __init__(self, group, agg, schema, sort=None, order=None, status=None,
                 query=None, archived=False):
        self.group = check_group(group)
        self.agg = check_aggregate(agg)
        self.key_of = key_of(group)
        self.schema, self.sort, self.descending = schema, sort, DESCENDING.get(order)
        self.filters = (status, query, archived)
        # The flat board's (sort, status, query, order, archived).
        self.flat = (sort, status, query, order, archived)
        self.metric = sort or primary_metric(schema)
        self._goal = metric_goal(schema, self.metric) if self.metric else None
        descending = self.descending
        if descending is None and self.metric:
            descending = sort_descending(schema, self.metric)
        self._sign = -1 if descending else 1

    def filtered(self, snapshot, rows):
        status, query, archived = self.filters
        return apply_filters(visible(rows, archived), status, query, snapshot)

    def carrying(self, rows):
        return sum(1 for row in rows if self.metric in row["metrics"])

    def row_key(self, position, present):
        """``(key, ranked)`` as :func:`order_key` orders the flat board."""
        return order_key(self.schema, self.sort, self.descending, lambda m: present, position)

    def value(self, summary):
        """A group's sort value: its aggregate, signed by the direction."""
        value = summary.value(self.metric, self.agg, self._goal)
        return None if value is None else self._sign * value


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
        self._total = None
        self._aggregates = {}  # memo: {group: aggregates payload}

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
            dirty.update(row["verstr"] for row in list(left) + list(joined))
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
            dirty.update(row["verstr"] for row in changed)
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
            return (first,)
        value = self.spec.value(self._summary(group))
        return (1, first) if value is None else (0, value, first)

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
        summary = self.summaries[group]
        if self.spec.group != RERUN_OF or group == NONE:
            return summary
        i = self.base.position.get(group)
        if i is None or (self.live is None and i in self._changed):
            return summary
        return summary.with_rows(self.spec.filtered(self.base.snapshot, [self.row_of(group)]))

    def _aggregates_of(self, group):
        found = self._aggregates.get(group)
        if found is None:
            found = self._aggregates[group] = self._summary(group).aggregates(self.spec.schema)
        return found

    def keys(self):
        return self.order + ([NONE] if NONE in self.members else [])

    @property
    def total(self):
        if self._total is None:
            self._total = sum(s.size for s in self.summaries.values())
        return self._total

    def group(self, key, offset, limit):
        """One group's payload, its rows paged."""
        rows = self.members[key]
        target = self.row_of(key) if self.spec.group in TARGET_LINKS and key != NONE else None
        return {"key": key, "label": label(self.spec.group, key, target is not None),
                "target": target_payload(target) if target else None,
                "counts": self.summaries[key].counts(),
                "aggregates": self._aggregates_of(key),
                "rows": list(rows[offset:offset + limit]), "rows_total": len(rows)}


def groups_payload(grouping, offset=0, limit=None, rows_per_group=10, group_key=None):
    """K1's answer: a page of groups, or with *group_key* one group's rows
    paged by *offset*/*limit* (:class:`UnknownGroup` when there is none)."""
    limit = 50 if limit is None else limit
    if group_key is not None:
        if group_key not in grouping.members:
            raise UnknownGroup(f"no group {group_key!r}")
        return grouping.group(group_key, offset, limit)
    keys = grouping.keys()
    return {"groups": [grouping.group(k, 0, rows_per_group) for k in keys[offset:offset + limit]],
            "total_groups": len(keys), "total_rows": grouping.total}
