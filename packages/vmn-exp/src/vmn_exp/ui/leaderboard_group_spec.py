#!/usr/bin/env python3
"""What one grouping of the grouped leaderboard (plan 22 K1) is: its field,
aggregate, sort and filters, and how it ranks rows and groups. A count sort
(``sort=c:total`` ..., :data:`~vmn_exp.ui.leaderboard_group_fields.COUNT_SORTS`)
orders groups by that count, most first unless ``order=asc``; its rows (and
ties) then take the default order, as with no sort (plan 22 F10).
"""
from vmn_exp.core.log import primary_metric, sort_descending
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.leaderboard_group_fields import (
    COUNT_SORTS,
    check_aggregate,
    check_group,
    key_of,
)
from vmn_exp.ui.leaderboard_live import order_key
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING
from vmn_exp.ui.readers.experiments import apply_filters


class GroupSpec:
    """One grouping's field, aggregate, sort and filters."""

    def __init__(self, group, agg, schema, sort=None, order=None, status=None,
                 query=None, archived=False):
        self.group = check_group(group)
        self.counted = COUNT_SORTS.get(sort)
        # The groups' order beyond the flat board's (a count sort), else None.
        self.group_sort = (sort, order) if self.counted else None
        if self.counted:
            self._count_sign = 1 if order == "asc" else -1
            sort = order = None
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

    def count(self, summary):
        """A group's count sort value, signed by the direction (None: no count sort)."""
        if not self.counted:
            return None
        counts = summary.counts()
        return self._count_sign * sum(counts[name] for name in self.counted)

    def value(self, summary):
        """A group's sort value: its aggregate, signed by the direction."""
        value = summary.value(self.metric, self.agg, self._goal)
        return None if value is None else self._sign * value
