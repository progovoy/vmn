#!/usr/bin/env python3
"""An outer run against its baseline (plan 28 N3), off a
:class:`~vmn_exp.ui.job_views.JobViews`: the choice
(:mod:`~vmn_exp.ui.baseline_choice`, by the app's ``experiment.ui.baseline``
rule unless the request names ``match``/``by``/``to``), the two job rollups'
deltas, the outer runs' own metrics, their direct children paired by key and
the chip (:mod:`~vmn_exp.ui.baseline_compare`), plus each attention query's
share under either subtree for the card.

The comparison is memoized per index snapshot and time bucket; a pair whose
two subtrees are settled (:mod:`~vmn_exp.ui.settled_subtree`) is kept
across generations until either changes, with an ETag of its own — a
finished launch and its baseline are compared once per process. Attention
shares (an ``ago()`` query follows the clock) are kept per generation
apart from it, so they never rebuild a settled pair. A child's main metric
is its own, else (an outer run) its subtree's best from the Jobs view's
summaries.
"""
import hashlib

from vmn_exp.core.app_settings import baseline_conf
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.similar_profile import objective_names
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.attention import attention_key, attention_payload
from vmn_exp.ui.baseline_choice import choose_baseline
from vmn_exp.ui.baseline_compare import best_chip, chip, delta, pair_children, rollup_deltas
from vmn_exp.ui.leaderboard_group_fields import value_of
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.settled_subtree import SettledMemo

SETTLED_PAIRS = 64
MAX_OWN_METRICS = 20
# Pairs a body lists (the chip counts them all): a pivot axis' worth.
MAX_PAIRS = 200


class UnknownBaseline(LookupError):
    """A ``to`` that is no outer run of the app."""


def _ref(row, source):
    return {"verstr": row["verstr"], "idx": row.get("idx"), "name": row.get("name"),
            "status": row.get("tree_status") or row.get("status"), "source": source,
            "started_at": row.get("started_at"), "finished_at": row.get("finished_at")}


def _directions(spec):
    """``{tracked metric: higher is better}`` (None for a goal-less rollup)."""
    return {m: spec.descending[m] if spec.ranked else None for m in spec.metrics}


def _own(row, base_row, schema):
    """The deltas of the metrics both outer runs log themselves."""
    ours, theirs = row.get("metrics") or {}, base_row.get("metrics") or {}
    names = sorted(n for n in objective_names(row) & objective_names(base_row)
                   if is_finite_number(ours[n]) and is_finite_number(theirs[n]))
    goal = lambda n: metric_goal(schema, n)  # noqa: E731
    return {n: delta(ours[n], theirs[n], None if goal(n) is None else goal(n) == "max")
            for n in names[:MAX_OWN_METRICS]}


def _share(count, total):
    return round(count / total, 4) if count is not None and total else None


def _share_parts(ours, theirs, total, base_total):
    """Attention parts of both subtrees as shares of their runs."""
    return [dict(a, baseline_count=b["count"],
                 **delta(_share(a["count"], total), _share(b["count"], base_total), False))
            for a, b in zip(ours, theirs)]


def _tag(*parts):
    return hashlib.blake2b(repr(parts).encode(), digest_size=16).hexdigest()


class BaselineViews:
    def __init__(self, views):
        self.views = views
        self._cache = views.cache
        track = self._cache.generations.track
        self._answers = track(LRU(256, name="baselines"))
        self._shares = track(LRU(64, name="baseline attention"))
        self._settled = SettledMemo(SETTLED_PAIRS, "settled baselines")

    def rule(self, snapshot, match=None, by=None):
        """``(match fields, children_by)``: the request's, else the app's rule
        (*by* ``""``: no pairing)."""
        conf = baseline_conf(self._cache.conf_of(snapshot)[1])
        fields = tuple(conf["match"] if match is None else match)
        return fields, (conf["children_by"] if by is None else by or None)

    def answer(self, snapshot, schema, verstr, to=None, match=None, by=None, attention=None):
        """``(payload, ETag)`` of job *verstr* against its baseline
        (*attention*: the app's entries, else no shares). Raises
        :class:`UnknownBaseline` for a bad *to*, ValueError for *to* = *verstr*."""
        body, tag = self._compared(snapshot, schema, verstr, to, self.rule(snapshot, match, by))
        if not attention or body["baseline"] is None:
            return body, tag
        pinned_key = tuple(map(tuple, attention_key(attention)))
        shares = self._attention(snapshot, schema, body, attention, pinned_key)
        return dict(body, attention=shares), _tag(tag, pinned_key)

    def baseline(self, snapshot, schema, verstr, **params):
        return self.answer(snapshot, schema, verstr, **params)[0]

    def etag(self, snapshot, schema, verstr, **params):
        return self.answer(snapshot, schema, verstr, **params)[1]

    def chips(self, snapshot, schema, verstrs, match=None, by=None):
        """``{verstr: chip with its baseline ref, or None}`` (None for no job
        or no baseline)."""
        rule, out = self.rule(snapshot, match, by), {}
        for v in verstrs:
            body = (self._compared(snapshot, schema, v, None, rule)[0]
                    if self.views.is_job(snapshot, v) else None)
            out[v] = body and body["chip"] and dict(body["chip"], baseline=body["baseline"])
        return out

    def chips_etag(self, snapshot, schema, verstrs, match=None, by=None):
        """:meth:`chips`' ETag: the board's (index generation, time bucket)."""
        rule = self.rule(snapshot, match, by)
        return self._cache.etag(snapshot, schema, route="baselines", key=(tuple(verstrs), rule))

    def _compared(self, snapshot, schema, verstr, to, rule):
        """``(payload without attention, ETag)``: per generation, else a
        settled pair's kept one, else built."""
        base, bucket = self._cache._base(snapshot)
        key = (verstr, to, rule, self._cache.schema_key(schema))
        return self._answers.get((base.token, bucket) + key,
                                 lambda: self._resolved(snapshot, schema, verstr, to, rule, key))

    def _resolved(self, snapshot, schema, verstr, to, rule, key):
        chosen = self._choose(snapshot, verstr, rule[0], to)
        base = self._cache._base(snapshot)[0]
        build = lambda: self._build(snapshot, schema, verstr, chosen, *rule)  # noqa: E731
        scopes = (verstr,) + ((chosen[0],) if chosen[0] else ())
        kept = self._settled.get(base, scopes, (snapshot.app_name, chosen) + key, build)
        if kept is not None:
            return kept
        return build(), self._cache.etag(snapshot, schema, route="baseline", key=key)

    def _choose(self, snapshot, verstr, fields, to):
        """``(baseline verstr or None, source)``."""
        if to is not None:
            if to == verstr:
                raise ValueError("an outer run is not its own baseline")
            if not self.views.is_job(snapshot, to):
                raise UnknownBaseline(f"{to} is not an outer run of this app")
            return to, "to"
        tree = self.views.rollups.tree(self._cache._base(snapshot)[0])
        target = self.views.row(snapshot, verstr)
        row, source = choose_baseline(target, self.views.rows_of(snapshot, tree.peers(verstr)),
                                      fields)
        return (row["verstr"], source) if row else (None, None)

    def _build(self, snapshot, schema, verstr, chosen, fields, by):
        row = self.views.row(snapshot, verstr)
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
        base_row = self.views.row(snapshot, base_v)
        rollups = self.views.rollups
        ours, theirs = (rollups.job_rollup(snapshot, schema, v) for v in (verstr, base_v))
        deltas = rollup_deltas(ours, theirs, _directions(spec))
        body.update(deltas, baseline=_ref(base_row, source), own=_own(row, base_row, schema))
        if by:
            body.update(self._paired(snapshot, schema, verstr, base_v, by, main, spec))
        else:
            body["chip"] = best_chip(deltas, main)
        return body

    def _paired(self, snapshot, schema, verstr, base_v, by, main, spec):
        value = self._child_value(snapshot, schema, main)
        kids = [self.views.children(snapshot, v) for v in (verstr, base_v)]
        up = spec.descending[main] if main else None
        pairs, total = pair_children(*kids, by, value, up)
        keyed = value_of(by)
        base_values = [value(r) for r in kids[1] if keyed(r) is not None]
        return {"pairs": pairs[:MAX_PAIRS], "pairs_total": total,
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

    def _attention(self, snapshot, schema, body, entries, pinned_key):
        """Each attention query's share under both subtrees, per generation."""
        base, bucket = self._cache._base(snapshot)
        pair = (body["verstr"], body["baseline"]["verstr"])
        key = (base.token, bucket, self._cache.schema_key(schema), pair, pinned_key)
        totals = [self.views.rollups.job_rollup(snapshot, schema, v)["total"] for v in pair]
        return self._shares.get(key, lambda: _share_parts(
            *(attention_payload(self._cache, snapshot, schema, entries, scope=v) for v in pair),
            *totals))
