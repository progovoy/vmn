#!/usr/bin/env python3
"""Keyset paging of the leaderboard (plan 23 S6).

A cursor carries the last :data:`TAIL` rows of the page it ends, each
projected onto the order's sort key (verstr, storage position, ``idx`` and
the sort value: a metric, a date, a ``job:*`` summary field), plus a
fingerprint of the request's sort and filters, so a cursor from another
order is refused. The next page starts strictly after the newest of those
rows still in the snapshot — its stored sort value at its current storage
position — found by bisection on the memoized order: O(log N) a page,
whatever joined, moved or left since. The cursor's own rows are left out,
so a gone last row resumes after the one before it without repeating any.
"""
import base64
import binascii
import hashlib
import json
from collections import ChainMap

from vmn_exp.core.field_sort import field_sort
from vmn_exp.core.log import DATE_SORTS, primary_metric
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.leaderboard_jobs import (
    JOB_SORTS,
    job_descending,
    job_key,
    job_value,
    sortable,
)
from vmn_exp.ui.leaderboard_live import bisect_key, order_key
from vmn_exp.ui.leaderboard_live_below import reads_live_below
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING

TAIL = 4


class BadCursor(ValueError):
    """A cursor that does not decode, or is from another sort or filter."""


def fingerprint(f, last, match_subtree):
    raw = json.dumps([list(f), last, bool(match_subtree)], default=str)
    return hashlib.blake2b(raw.encode(), digest_size=6).hexdigest()


def encode(fp, projs):
    raw = json.dumps([fp, projs], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor, fp):
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        got, projs = json.loads(raw)
        ok = projs and all(isinstance(p, list) and len(p) >= 4 and isinstance(p[0], str)
                           and isinstance(p[1], int) for p in projs)
    except (binascii.Error, ValueError, TypeError):
        raise BadCursor("malformed cursor")
    if not ok:
        raise BadCursor("malformed cursor")
    if got != fp:
        raise BadCursor("cursor is from another sort or filter")
    return projs


class RowKey:
    """:func:`~vmn_exp.ui.leaderboard_live.order_key` of one order, and the
    key a cursor row's projection stands for."""

    def __init__(self, schema, sort, order, present, base, projs=()):
        self.base = base
        position = ChainMap(base.position, {p[0]: p[1] for p in projs})
        self.key, ranked = order_key(schema, sort, DESCENDING.get(order), present, position)
        self.field = field_sort(sort)
        self.kind = ("date" if sort in DATE_SORTS else "field" if self.field
                     else "metric" if ranked else None)
        self.name = sort if self.kind == "date" else sort or primary_metric(schema)

    def has(self, verstr):
        return verstr in self.base.position

    def _value(self, row):
        if self.kind == "metric":
            value = row["metrics"].get(self.name)
            return value if is_finite_number(value) else None
        if self.kind == "field":
            return self.field.raw(row)
        return row.get(self.name) or None if self.kind == "date" else None

    def project(self, row):
        return [row["verstr"], self.base.position[row["verstr"]], row["idx"], self._value(row)]

    def target(self, proj):
        verstr, _, idx, value = proj[:4]
        at = self.base.position.get(verstr)
        row = {"verstr": verstr, "metrics": {},
               "idx": idx if at is None else self.base.rows[at]["idx"]}
        if self.kind == "metric" and value is not None:
            row["metrics"][self.name] = value
        elif self.kind == "date":
            row[self.name] = value
        elif self.kind == "field":
            row.update(self.field.placed(value))
        return self.key(row)


class JobKey:
    """A ``job:*`` order's key: the summary field, then the default order's."""

    def __init__(self, inner, summaries, field, descending):
        self.inner, self.summaries = inner, summaries
        self.field, self.descending = field, descending
        self.has = inner.has

    def _value(self, row):
        return job_value(self.summaries, row, self.field)

    def key(self, row):
        return job_key(self._value(row), self.descending, self.inner.key(row))

    def project(self, row):
        return self.inner.project(row) + [self._value(row)]

    def target(self, proj):
        value = proj[4] if len(proj) > 4 and sortable(proj[4]) else None
        return job_key(value, self.descending, self.inner.target(proj))


def keyed(cache, snapshot, schema, last, f, projs, attention=()):
    """The sort key of the order *cache* serves for *last* and the filters *f*
    (and the *attention* queries a ``job:attention`` sort ranks by)."""
    plain = f._replace(sort=None, order=None) if f.sort in JOB_SORTS else f
    base = cache._base(snapshot)[0]
    present = _presence(cache, snapshot, schema, last, plain)
    key = RowKey(schema, plain.sort, plain.order, present, base, projs)
    if f.sort not in JOB_SORTS:
        return key
    summaries = cache._job_view.summaries(snapshot, schema, f.sort, attention, f.children_of)
    field = JOB_SORTS[f.sort]
    return JobKey(key, summaries, field, job_descending(field, f.order, summaries, schema))


def _presence(cache, snapshot, schema, last, f):
    """Whether a metric ranks the order (some filtered row carries it); a
    ``live_below`` top query's is the order's it filters."""
    if reads_live_below(f.top_query):
        f = f._replace(top_query=None)
    rows = cache._ordered(snapshot, schema, last, f)
    if last:
        return lambda m: any(m in r["metrics"] for r in rows)
    static = cache.static_order(cache._base(snapshot)[0], schema, f)
    live = getattr(rows, "live", ())
    return lambda m: static.has_metric or any(m in r["metrics"] for r in live)


class Pager:
    """One page's cut: by *cursor* when given (else *offset*), and the next cursor."""

    def __init__(self, keyer, fp, cursor=None):
        self._keyer = keyer  # projections -> key
        self.fp = fp
        self.projs = [] if cursor is None else decode(cursor, fp)

    def cut(self, rows, offset, limit):
        """``(rows of the page, next cursor or None)``."""
        projs, key = self.projs, None
        start, skip = offset, set()
        if projs:
            key = self._keyer(projs)
            anchor = next((p for p in reversed(projs) if key.has(p[0])), projs[-1])
            start = bisect_key(rows, key.target(anchor), key.key, right=True)
            skip = {p[0] for p in projs}
        cut, at = [], start
        for row in rows[start : start + limit + len(skip)]:
            if len(cut) == limit:
                break
            at += 1
            if row["verstr"] not in skip:
                cut.append(row)
        if at >= len(rows) or not (cut or projs):
            return cut, None
        key = key or self._keyer(projs)
        return cut, encode(self.fp, (projs + [key.project(row) for row in cut])[-TAIL:])
