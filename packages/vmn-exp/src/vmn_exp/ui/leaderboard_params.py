#!/usr/bin/env python3
"""``list_experiments``' query parameters, grouped by what they select
(plan 42 E12d): the page and its filters, grouping, the tree page and the
Jobs view's aggregate. :func:`resolve_mode` names the answer's
:class:`Mode` or refuses a combination with a 400 naming the parameters
that conflict. The groups are FastAPI ``Depends()`` classes, so the URL and
the unknown-parameter refusal (:mod:`~vmn_exp.ui.query_params`) stay as
they were."""
from dataclasses import dataclass
from typing import NamedTuple

from fastapi import HTTPException

FLAT, GROUPED, TREE = "flat", "grouped", "tree"


class Mode(NamedTuple):
    """The answer's shape (:data:`FLAT`, :data:`GROUPED`, :data:`TREE`)
    and whether its rows are top-level runs with ``job`` summaries."""
    shape: str
    jobs: bool


@dataclass
class PageParams:
    sort: str = None
    last: int = None
    offset: int = 0
    limit: int = None
    status: str = None
    q: str = None
    order: str = None
    archived: bool = False
    scope: str = None
    top: str = None
    top_q: str = None
    match_subtree: bool = False
    cursor: str = None


@dataclass
class GroupParams:
    group: str = None
    agg: str = None
    rows_per_group: int = 10
    group_key: str = None
    collapse_all: bool = False


@dataclass
class TreeParams:
    children_of: str = None


@dataclass
class JobAggParams:
    job_agg: str = None
    job_agg_by: str = None
    job_agg_value: str = None
    job_agg_metric: str = None
    job_agg_nested: bool = None

    def given(self):
        """The values as :func:`~vmn_exp.ui.job_aggregate.job_agg_of` takes them."""
        return dict(agg=self.job_agg, by=self.job_agg_by, value=self.job_agg_value,
                    metric=self.job_agg_metric, nested=self.job_agg_nested)


def resolve_mode(page, group, tree, job_agg, top, by_comments):
    """The :class:`Mode` of a request whose ``top`` parsed to *top* and
    whose ``q`` reads comments when *by_comments*; a 400 for a combination
    the route refuses."""
    grouped = group.group is not None
    if page.top_q and not top:
        _refuse("top_q needs top=1")
    if group.collapse_all and not (top and grouped):
        _refuse("collapse_all needs group and top")
    if not top and any(value is not None for value in job_agg.given().values()):
        _refuse("job_agg needs top=1")
    jobs = bool(top)
    if tree.children_of is not None:
        if grouped:
            _refuse("children_of cannot be combined with group")
        if by_comments:
            _refuse("children_of cannot be combined with a comments query")
        return Mode(TREE, jobs)
    if grouped:
        if page.last or page.cursor is not None:
            _refuse("last and cursor cannot be combined with group")
        return Mode(GROUPED, jobs)
    return Mode(FLAT, jobs)


def _refuse(reason):
    raise HTTPException(400, reason)
