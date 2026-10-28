#!/usr/bin/env python3
"""An outer run against its baseline (plan 28 N3), off a
:class:`~vmn_exp.ui.job_views.JobViews`: the choice
(:mod:`~vmn_exp.ui.baseline_choice`, by the app's ``experiment.ui.baseline``
rule unless the request names ``match``/``by``/``to``), the two job rollups'
deltas, each attention query's share under either subtree, the outer runs'
own metrics, their direct children paired by key and the chip
(:mod:`~vmn_exp.ui.baseline_compare`).

Memoized per index snapshot and time bucket; a pair whose two subtrees are
settled (:mod:`~vmn_exp.ui.settled_subtree`) is kept across generations
until either changes, with an ETag of its own — a finished launch and its
baseline are compared once per process. A child's main metric is its own,
else (an outer run) its subtree's best from the Jobs view's summaries.
"""
import hashlib
import itertools
import os

from vmn_exp.core.app_settings import baseline_conf
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.query import QueryError
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.attention import attention_key, pinned
from vmn_exp.ui.baseline_choice import choose_baseline
from vmn_exp.ui.baseline_compare import best_chip, chip, delta, pair_children, rollup_deltas
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.leaderboard_group_fields import value_of
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.settled_subtree import same_rows, settled, subtree_rows

SETTLED_PAIRS = 64
MAX_OWN_METRICS = 20
_NONCE = os.urandom(8).hex()


class UnknownBaseline(LookupError):
    """A ``to`` that is no outer run of the app."""


def _parent(row):
    parent = row.get("parent")
    return parent if parent and parent != row["verstr"] else None


def _higher_better(schema, name):
    goal = metric_goal(schema, name)
    return None if goal is None else goal == "max"


def _ref(row, source):
    return {"verstr": row["verstr"], "idx": row.get("idx"), "name": row.get("name"),
            "status": row.get("tree_status") or row.get("status"), "source": source,
            "started_at": row.get("started_at"), "finished_at": row.get("finished_at")}


def _own(row, base_row, schema):
    """The deltas of the metrics both outer runs log themselves (not folded params)."""
    ours, theirs = row.get("metrics") or {}, base_row.get("metrics") or {}
    params = set(row.get("params") or {}) | set(base_row.get("params") or {})
    names = sorted(n for n in ours if n in theirs and n not in params and not n.startswith("sys_")
                   and is_finite_number(ours[n]) and is_finite_number(theirs[n]))
    return {n: delta(ours[n], theirs[n], _higher_better(schema, n))
            for n in names[:MAX_OWN_METRICS]}


class BaselineViews:
    def __init__(self, views):
        self.views = views
        self._cache = views.cache
        track = self._cache.generations.track
        self._peers = track(LRU(16, name="baseline peers"))
        self._choices = track(LRU(256, name="baseline choices"))
        self._answers = track(LRU(256, name="baselines"))
        self._settled = LRU(SETTLED_PAIRS, name="settled baselines")
        self._serials = itertools.count(1)

    def rule(self, snapshot, match=None, by=None):
        """``(match fields, children_by)``: the request's, else the app's rule
        (*by* ``""``: no pairing)."""
        conf = baseline_conf(self._cache.conf_of(snapshot)[1])
        fields = tuple(conf["match"] if match is None else match)
        return fields, (conf["children_by"] if by is None else by or None)

    def baseline(self, snapshot, schema, verstr, to=None, match=None, by=None, attention=None):
        """The comparison payload of job *verstr* (*attention*: the app's
        entries, else no shares). Raises :class:`UnknownBaseline` for a bad
        *to*, ValueError for *to* = *verstr*."""
        return self._entry(snapshot, schema, verstr, to, match, by, attention)[0]

    def etag(self, snapshot, schema, verstr, to=None, match=None, by=None, attention=None):
        return self._entry(snapshot, schema, verstr, to, match, by, attention)[1]

    def chips(self, snapshot, schema, verstrs, match=None, by=None):
        """``{verstr: chip with its baseline ref, or None}`` (None for no job
        or no baseline)."""
        jobs = self.views.rollups.tree(self._cache._base(snapshot)[0]).jobs
        out = {}
        for v in verstrs:
            body = self.baseline(snapshot, schema, v, match=match, by=by) if v in jobs else None
            out[v] = body and body["chip"] and dict(body["chip"], baseline=body["baseline"])
        return out

    def chips_etag(self, snapshot, schema, verstrs, match=None, by=None):
        """:meth:`chips`' ETag: the board's (index generation, time bucket)."""
        rule = self.rule(snapshot, match, by)
        return self._cache.etag(snapshot, schema, route="baselines", key=(tuple(verstrs), rule))

    def _entry(self, snapshot, schema, verstr, to, match, by, attention):
        """``(payload, ETag)``."""
        fields, by = self.rule(snapshot, match, by)
        chosen = self._choose(snapshot, verstr, fields, to)
        akey = None if attention is None else tuple(map(tuple, attention_key(attention)))
        key = (verstr, chosen, fields, by, akey, self._cache.schema_key(schema))
        build = lambda: self._build(snapshot, schema, verstr, chosen, fields, by, attention)  # noqa: E731
        base, bucket = self._cache._base(snapshot)
        pair = (verstr,) + ((chosen[0],) if chosen[0] else ())
        if all(settled(base, v) for v in pair):
            rows = [row for v in pair for row in subtree_rows(base, v)]
            hit = self._settled.get((snapshot.app_name,) + key,
                                    lambda: (rows, build(), next(self._serials)),
                                    valid=lambda kept: same_rows(kept[0], rows))
            tag = hashlib.blake2b(f"{_NONCE}:{hit[2]}".encode(), digest_size=16).hexdigest()
            return hit[1], tag
        body = self._answers.get((base.token, bucket) + key, build)
        return body, self._cache.etag(snapshot, schema, route="baseline", key=key)

    def _choose(self, snapshot, verstr, fields, to):
        """``(baseline verstr or None, source)``."""
        base, bucket = self._cache._base(snapshot)
        return self._choices.get((base.token, bucket, verstr, fields, to),
                                 lambda: self._chosen(snapshot, base, verstr, fields, to))

    def _chosen(self, snapshot, base, verstr, fields, to):
        if to is not None:
            if to == verstr:
                raise ValueError("an outer run is not its own baseline")
            if to not in self.views.rollups.tree(base).jobs:
                raise UnknownBaseline(f"{to} is not an outer run of this app")
            return to, "to"
        target = self.views._row(snapshot, verstr)
        peers = self._peers.get(base.token, lambda: self._peers_of(base))
        rows = [self.views._row(snapshot, v) for v in peers.get(_parent(target), ())]
        row, source = choose_baseline(target, visible(rows, False), fields)
        return (row["verstr"], source) if row else (None, None)

    def _peers_of(self, base):
        """``{parent: [its jobs]}`` (top-level jobs under None)."""
        out = {}
        for job in self.views.rollups.tree(base).jobs:
            out.setdefault(_parent(base.rows[base.position[job]]), []).append(job)
        return out

    def _build(self, snapshot, schema, verstr, chosen, fields, by, attention):
        row = self.views._row(snapshot, verstr)
        spec = self.views.rollups.spec(snapshot, schema)
        main = spec.main if spec.ranked else None
        body = {"verstr": verstr, "match": list(fields), "by": by,
                "values": {f: value_of(f)(row) for f in fields}, "baseline": None,
                "metric": spec.main, "goal": metric_goal(schema, spec.main) if main else None,
                "metrics": {}, "failed_pct": None, "duration_p90": None, "attention": [],
                "own": {}, "pairs": [], "pairs_total": 0, "chip": None}
        base_v, source = chosen
        if base_v is None:
            return body
        base_row = self.views._row(snapshot, base_v)
        rollups = self.views.rollups
        ours, theirs = (rollups.job_rollup(snapshot, schema, v) for v in (verstr, base_v))
        directions = {m: _higher_better(schema, m) if spec.ranked else None for m in spec.metrics}
        deltas = rollup_deltas(ours, theirs, directions)
        body.update(deltas, baseline=_ref(base_row, source), own=_own(row, base_row, schema))
        if attention:
            body["attention"] = self._shares(snapshot, schema, attention, verstr, base_v,
                                             ours["total"], theirs["total"])
        if by:
            body.update(self._paired(snapshot, schema, verstr, base_v, by, main))
        else:
            body["chip"] = best_chip(deltas, main)
        return body

    def _paired(self, snapshot, schema, verstr, base_v, by, main):
        value = self._child_value(snapshot, schema, main)
        kids = [self.views.children(snapshot, v) for v in (verstr, base_v)]
        up = _higher_better(schema, main) if main else None
        pairs, total = pair_children(*kids, by, value, up)
        keyed = value_of(by)
        base_values = [value(r) for r in kids[1] if keyed(r) is not None]
        return {"pairs": pairs, "pairs_total": total,
                "chip": chip(pairs, base_values, main, up, by)}

    def _child_value(self, snapshot, schema, main):
        """``row -> its main metric``: its own, else its subtree's best."""
        if main is None:
            return lambda row: None
        summaries = self._cache.job_rollups(snapshot, schema)

        def value(row):
            own = (row.get("metrics") or {}).get(main)
            if is_finite_number(own):
                return own
            return (summaries.get(row["verstr"]) or {}).get("best")
        return value

    def _shares(self, snapshot, schema, entries, verstr, base_v, total, base_total):
        out = []
        for e in entries:
            part = {"key": e["key"], "label": e["label"], "level": e["level"], "q": e["query"]}
            try:
                n, m = (len(self._cache.ordered(snapshot, schema, query=pinned(e["query"]),
                                                scope=v)) for v in (verstr, base_v))
            except QueryError as exc:
                out.append(dict(part, count=None, baseline_count=None, error=str(exc),
                                **delta(None, None, False)))
                continue
            share = lambda k, of: round(k / of, 4) if of else None  # noqa: E731
            out.append(dict(part, count=n, baseline_count=m,
                            **delta(share(n, total), share(m, base_total), False)))
        return out
