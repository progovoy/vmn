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
apart from it, so they never rebuild a settled pair. A child's value is
the Outer runs row's (plan 31 §2, :mod:`~vmn_exp.ui.job_aggregate`): the
app's ``job_aggregate`` metric, its own or its subtree's best by the
aggregate's ``value``, the same source on both sides (plan 32); the chip
without pairs compares the two jobs' ``rolled``.

With ``pool_by`` (plan 35 §3, e.g. ``tags.launch_id``) a run is compared
through its training: the outer runs beside it sharing its value, the latest
attempt first (:func:`~vmn_exp.ui.leaderboard_group_jobs.attempt_order`).
The baseline is another training, chosen on each training's latest attempt;
both sides' children pair by key with the latest attempt holding a key
winning it, and ``rolled`` is both trainings' pooled units (the grouped
header's :meth:`~vmn_exp.ui.job_aggregate.JobAggregates.pooled`). The
rollup deltas stay the two latest attempts'. A run without the field has no
baseline (missing is missing).
"""
import hashlib
from typing import NamedTuple, Optional, Tuple

from vmn_exp.core.app_settings import baseline_rule
from vmn_exp.core.metric_schema import higher_is_better, metric_goal
from vmn_exp.core.similar_profile import objective_names
from vmn_exp.ui.job_aggregate import board_job_agg
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.attention import attention_key, attention_payload
from vmn_exp.ui.baseline_choice import choose_baseline
from vmn_exp.ui.baseline_compare import best_chip, chip, delta, pair_children, rollup_deltas
from vmn_exp.ui.leaderboard_group_fields import NONE, key_of, value_of
from vmn_exp.ui.leaderboard_group_jobs import attempt_order
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.settled_subtree import SettledMemo

SETTLED_PAIRS = 64
MAX_OWN_METRICS = 20
# Pairs a body lists (the chip counts them all): a pivot axis' worth.
MAX_PAIRS = 200


class Rule(NamedTuple):
    """How a baseline is chosen and paired; a memo key part."""
    match: Tuple[str, ...]
    by: Optional[str]
    differ: Tuple[str, ...]
    pool_by: Optional[str] = None


class UnknownBaseline(LookupError):
    """A ``to`` that is no outer run of the app."""


def _ref(row, source):
    return {"verstr": row["verstr"], "idx": row.get("idx"), "name": row.get("name"),
            "status": row.get("tree_status") or row.get("status"), "source": source,
            "started_at": row.get("started_at"), "finished_at": row.get("finished_at")}


def _own(row, base_row, schema):
    """The deltas of the metrics both outer runs log themselves."""
    ours, theirs = row.get("metrics") or {}, base_row.get("metrics") or {}
    names = sorted(n for n in objective_names(row) & objective_names(base_row)
                   if is_finite_number(ours[n]) and is_finite_number(theirs[n]))
    return {n: delta(ours[n], theirs[n], higher_is_better(metric_goal(schema, n)))
            for n in names[:MAX_OWN_METRICS]}


def _share(count, total):
    return round(count / total, 4) if count is not None and total else None


def _share_parts(ours, theirs, total, base_total):
    """Attention parts of both subtrees as shares of their runs, paired by
    key: a built-in part shown on one side only (it hides at 0) counts 0 on
    the other."""
    mine = {part["key"]: part for part in ours}
    base = {part["key"]: part for part in theirs}
    parts = [*ours, *(dict(part, count=0) for part in theirs if part["key"] not in mine)]
    return [dict(a, baseline_count=_count_of(base.get(a["key"])),
                 **delta(_share(a["count"], total),
                         _share(_count_of(base.get(a["key"])), base_total), False))
            for a in parts]


def _count_of(part):
    return 0 if part is None else part["count"]


def _latest_first(rows):
    return tuple(row["verstr"] for row in sorted(rows, key=attempt_order, reverse=True))


def _trainings(rows, field):
    """``{key: (verstr, ...)}``: *rows* by their *field*, the latest attempt
    first; rows without it are in none."""
    key_in, out = key_of(field), {}
    for row in rows:
        key = key_in(row)
        if key != NONE:
            out.setdefault(key, []).append(row)
    return {key: _latest_first(kept) for key, kept in out.items()}


def _training(trainings, field, row):
    """*row*'s attempts in *trainings* (by *field*), else *row* alone."""
    return trainings.get(key_of(field)(row), (row["verstr"],))


def _pooled_children(sides, field):
    """The children of each attempt of *sides* (the latest first) holding a
    *field* key no later attempt holds: a key from the latest attempt with it."""
    key_in, taken, out = key_of(field), set(), []
    for kids in sides:
        keys = {key_in(row) for row in kids} - {NONE}
        out += [row for row in kids if key_in(row) in keys - taken]
        taken |= keys
    return out


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
        """The :class:`Rule`: the request's *match*/*by*, else the app's
        (*by* ``""``: no pairing); ``differ`` is always the app's."""
        conf = baseline_rule(self._cache.conf_of(snapshot)[1])
        return Rule(tuple(conf["match"] if match is None else match),
                    conf["children_by"] if by is None else by or None, tuple(conf["differ"]),
                    conf["pool_by"])

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
        key = (verstr, to, rule, self._cache.schema_key(schema),
               board_job_agg(self._cache, snapshot))
        return self._answers.get((base.token, bucket) + key,
                                 lambda: self._resolved(snapshot, schema, verstr, to, rule, key))

    def _resolved(self, snapshot, schema, verstr, to, rule, key):
        chosen, sides = self._choose(snapshot, verstr, rule, to)
        base = self._cache._base(snapshot)[0]
        build = lambda: self._build(snapshot, schema, verstr, chosen, rule, sides)  # noqa: E731
        scopes = sides[0] + sides[1]
        kept = self._settled.get(base, scopes, (snapshot.app_name, chosen) + key, build)
        if kept is not None:
            return kept
        return build(), self._cache.etag(snapshot, schema, route="baseline", key=key)

    def _choose(self, snapshot, verstr, rule, to):
        """``((baseline verstr or None, source), (our attempts, theirs))``,
        the attempts latest first: the two runs alone without ``pool_by``."""
        if to is not None:
            if to == verstr:
                raise ValueError("an outer run is not its own baseline")
            if not self.views.is_job(snapshot, to):
                raise UnknownBaseline(f"{to} is not an outer run of this app")
        tree = self.views.rollups.tree(self._cache._base(snapshot)[0])
        target = self.views.row(snapshot, verstr)
        peers = self.views.rows_of(snapshot, tree.peers(verstr))
        trainings = _trainings(peers, rule.pool_by) if rule.pool_by else {}
        ours = _training(trainings, rule.pool_by, target) if rule.pool_by else (verstr,)
        if to is not None:
            theirs = (_training(trainings, rule.pool_by, self.views.row(snapshot, to))
                      if rule.pool_by else (to,))
            return (to, "to"), (ours, theirs)
        if rule.pool_by:
            mine = key_of(rule.pool_by)(target)
            if mine == NONE:
                return (None, None), (ours, ())
            target = self.views.row(snapshot, ours[0])
            peers = [self.views.row(snapshot, kept[0]) for key, kept in trainings.items()
                     if key != mine]
        row, source = choose_baseline(target, peers, rule.match, rule.differ)
        if row is None:
            return (None, None), (ours, ())
        theirs = trainings[key_of(rule.pool_by)(row)] if rule.pool_by else (row["verstr"],)
        return (row["verstr"], source), (ours, theirs)

    def _build(self, snapshot, schema, verstr, chosen, rule, sides):
        fields, by = rule.match, rule.by
        row = self.views.row(snapshot, verstr)
        spec = self.views.rollups.spec(snapshot, schema)
        body = {"verstr": verstr, "match": list(fields), "differ": list(rule.differ), "by": by,
                "values": {f: value_of(f)(row) for f in fields}, "baseline": None,
                "metric": spec.main, "goal": spec.goals.get(spec.main),
                "metrics": {}, "failed_pct": None, "duration_p90": None, "attention": [],
                "own": {}, "pairs": [], "pairs_total": 0, "chip": None,
                "pool_by": rule.pool_by, "pool": None}
        base_v, source = chosen
        if base_v is None:
            return body
        base_row = self.views.row(snapshot, base_v)
        rollups, aggregates = self.views.rollups, self._cache.job_aggregates
        ours, theirs = (rollups.job_rollup(snapshot, schema, v) for v in (verstr, base_v))
        if rule.pool_by:
            rolled = [aggregates.pooled(snapshot, schema, side) for side in sides]
            body["pool"] = {"by": rule.pool_by, "attempts": list(sides[0]),
                            "baseline_attempts": list(sides[1])}
        else:
            rolled = [aggregates.one(snapshot, schema, v) for v in (verstr, base_v)]
        deltas = rollup_deltas(ours, theirs, spec.goals, rolled)
        body.update(deltas, baseline=_ref(base_row, source), own=_own(row, base_row, schema))
        if by:
            body.update(self._paired(snapshot, schema, sides, by, rule.pool_by))
        else:
            body["chip"] = best_chip(deltas)
        if body["chip"] and rule.pool_by:
            body["chip"]["pool_by"] = rule.pool_by
        return body

    def _paired(self, snapshot, schema, sides, by, pool_by):
        """The children of both *sides* (each its attempts, the latest
        first) paired by *by* with their values' deltas (the board's value
        function); a goal-less metric pairs without a direction and has no
        chip."""
        unit = self._cache.job_aggregates.value_of(snapshot, schema)
        kids = [_pooled_children([self.views.children(snapshot, v) for v in side], by)
                for side in sides]
        values = {row["verstr"]: unit.of_row(row) for side in kids for row in side}
        value = lambda row: values[row["verstr"]]  # noqa: E731
        pairs, total = pair_children(*kids, by, value, unit.up)
        keyed = value_of(by)
        base_values = [value(r) for r in kids[1] if keyed(r) is not None]
        return {"pairs": pairs[:MAX_PAIRS], "pairs_total": total,
                "chip": chip(pairs, base_values, unit.metric, unit.up, by, total, bool(pool_by))}

    def _attention(self, snapshot, schema, body, entries, pinned_key):
        """Each attention query's share under both subtrees, per generation."""
        base, bucket = self._cache._base(snapshot)
        pair = (body["verstr"], body["baseline"]["verstr"])
        key = (base.token, bucket, self._cache.schema_key(schema), pair, pinned_key)
        totals = [self.views.rollups.job_rollup(snapshot, schema, v)["total"] for v in pair]
        return self._shares.get(key, lambda: _share_parts(
            *(attention_payload(self._cache, snapshot, schema, entries, scope=v) for v in pair),
            *totals))
