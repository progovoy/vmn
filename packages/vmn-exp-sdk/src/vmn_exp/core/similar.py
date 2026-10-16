#!/usr/bin/env python3
"""Similar runs: "has anyone run something like this before?" (plan 24).

:func:`similar_runs_multi` ranks the runs of one or more :class:`Scope`\\ s
(:mod:`vmn_exp.core.similar_corpus`) against a *target* —

    {"row": row | None, "features": dict | None, "intent": dict | None,
     "hypothesis": str | None, "text": str | None, "text_only": bool,
     "command": argv?, "create_note": str?, "app": str?}

a run (:func:`target_from_snapshot`) or a working tree (a row-like dict
without a verstr, or None). ``text`` replaces the target's text document
(``--context``); ``text_only`` matches that text alone. FTS5 ranks: the
target's document becomes one MATCH (:mod:`vmn_exp.core.similar_match`),
scored by bm25 under the signal weights as column weights, a page of
:data:`PAGE` at a time. The target is left out, with its whole tree (its
outer run, every run under it) and its reruns — runs of its rerun identity
(:func:`~vmn_exp.core.similar_profile.rerun_key`) but a fork of it or the run
it forked from — in the target's ``app`` only, when given.

Results are grouped — the runs of one tree, else of one rerun identity — so a
sweep or the reruns of one config fill one slot, shown by the member best on
the group's goal metric (:func:`goal_metric`), else the most similar — a
container (a run with inner runs) only when the group holds nothing else;
``group_size`` counts the members found. Items sort by score, then newest,
then verstr; scores are bm25 relative to the best run found (1.0; the
target and the runs it excludes aside), never stored; a process asking again
over unchanged documents reuses its match and pages (:func:`_memoized`).
Reasons and signals are computed for the items returned only
(:mod:`vmn_exp.core.similar_reasons`). A *deadline* (a :func:`time.monotonic`
value) interrupts the SQLite work: :class:`SimilarDeadlineExceeded`.
"""
import threading
from collections import Counter, OrderedDict

from vmn_exp.core import similar_fts
from vmn_exp.core.metric_schema import effective_schema, metric_goal
from vmn_exp.core.similar_corpus import Scope, as_scope  # noqa: F401  (Scope: re-exported)
from vmn_exp.core.similar_doc import build_doc
from vmn_exp.core.similar_filing import snapshot_facts
from vmn_exp.core.similar_match import (
    SimilarDeadlineExceeded,  # noqa: F401  (re-exported)
    build_match,
    rank,
)
from vmn_exp.core.similar_match import deadline as deadline_guard
from vmn_exp.core.similar_profile import objective_names
from vmn_exp.core.similar_reasons import Explainer
from vmn_exp.core.similar_weights import column_weights, resolve_weights
from vmn_exp.core.values import is_finite_number

PAGE = 500
_MEMO_SIZE = 256
_MEMO = OrderedDict()  # (scope cache key, what) -> a Match or a ranked page
_MEMO_LOCK = threading.Lock()


def _memoized(scope, what, compute):
    """*compute()*, remembered for scopes of one :attr:`Scope.cache_key`
    (documents unchanged since): a warm process asks SQLite once."""
    if scope.cache_key is None:
        return compute()
    key = (scope.cache_key, what)
    with _MEMO_LOCK:
        if key in _MEMO:
            _MEMO.move_to_end(key)
            return _MEMO[key]
    value = compute()
    with _MEMO_LOCK:
        _MEMO[key] = value
        while len(_MEMO) > _MEMO_SIZE:
            _MEMO.popitem(last=False)
    return value


def target_from_snapshot(snapshot, verstr, text=None, text_only=False, *, app=None):
    """The target dict of the run *verstr* of *snapshot*; KeyError when absent.
    *app* names the snapshot's app, so that over several apps the target's
    exclusions apply in its own only."""
    lookup = getattr(snapshot, "row", None)
    row = lookup(verstr) if callable(lookup) else next(
        (r for r in snapshot.rows if r["verstr"] == verstr), None)
    if row is None:
        raise KeyError(verstr)
    features, intent, hypothesis, command, note = snapshot_facts(snapshot, row)
    target = {"row": row, "features": features, "intent": intent, "hypothesis": hypothesis,
              "text": text, "text_only": bool(text_only), "command": command,
              "create_note": note}
    if app is not None:
        target["app"] = app
    return target


def goal_metric(schema, rows):
    """``(metric, goal)`` *rows* are ranked on: of their objective metrics
    with a goal in *schema*, the one most rows carry (then by name); None."""
    if not schema:
        return None
    counts = Counter()
    for row in rows:
        metrics = row.get("metrics") or {}
        counts.update(n for n in objective_names(row) if is_finite_number(metrics.get(n)))
    for name in sorted(counts, key=lambda n: (-counts[n], n)):
        goal = metric_goal(schema, name)
        if goal:
            return name, goal
    return None


class _Query:
    """A target, read once: its document, weights and the columns it asks."""

    def __init__(self, target, weights=None):
        row = target.get("row") or {}
        self.row, self.verstr, self.app = row, row.get("verstr"), target.get("app")
        self.text_only = bool(target.get("text_only"))
        self.doc = build_doc(row, target.get("features"), target.get("intent"),
                             target.get("hypothesis"), command=target.get("command"),
                             create_note=target.get("create_note") or row.get("create_note"),
                             text=target.get("text"))
        weights = resolve_weights(weights, intent=self.doc.has_intent)
        self.weights = {"text": weights["text"]} if self.text_only else weights
        self.columns = column_weights(self.weights)

    def excludes(self, scope):
        """``excluded(row, rerun key)`` in *scope*; None when it excludes nothing."""
        if not self.verstr or self.app not in (None, scope.label):
            return None
        root = scope.rows.root(self.row)

        def excluded(row, rerun):
            if row["verstr"] == self.verstr or scope.rows.root(row) == root:
                return True
            return (self.doc.rerun is not None and rerun == self.doc.rerun
                    and row.get("forked_from") != self.verstr
                    and self.row.get("forked_from") != row["verstr"])
        return excluded


class _Search:
    """One scope's groups for a query (see the module docstring)."""

    def __init__(self, scope, query, rows_filter):
        self.scope, self.query, self.rows_filter = scope, query, rows_filter
        self.match = None

    def groups(self, top):
        conn, scope = self.scope.conn, self.scope
        columns = tuple(c for c, w in self.query.columns.items() if w > 0)
        doc = self.query.doc
        asked = ("match", columns, doc.text, tuple(sorted(doc.cols.items())))
        self.match = _memoized(scope, asked, lambda: build_match(conn, doc, columns))
        expression = self.match.expression()
        if expression is None:
            return []
        excluded = self.query.excludes(scope)
        groups, offset, size = {}, 0, PAGE
        while True:
            asked = ("rank", scope.app, expression, tuple(sorted(self.query.columns.items())),
                     offset, size)
            page, more = _memoized(scope, asked, lambda: rank(
                conn, scope.app, expression, self.query.columns, offset, size))
            self._group(page, excluded, groups)
            if not more or len(groups) >= top:
                break
            offset, size = offset + size, size * 2
        return [self._item(members) for members in groups.values()]

    def _group(self, page, excluded, groups):
        verstrs = [v for v, _ in page]
        rows = self.scope.rows.rows_of(verstrs)
        reruns = similar_fts.reruns_of(self.scope.conn, self.scope.app, verstrs)
        parents = self.scope.rows.parents_among(verstrs)
        for verstr, score in page:
            row = rows.get(verstr)
            if row is None or (excluded and excluded(row, reruns.get(verstr))):
                continue
            if self.rows_filter is not None and not self.rows_filter(self.scope.label, row):
                continue
            if row.get("parent") or verstr in parents:
                key = ("tree", self.scope.rows.root(row))
            else:
                key = ("rerun", reruns[verstr]) if reruns.get(verstr) else ("run", verstr)
            groups.setdefault(key, []).append({
                "scope": self, "app": self.scope.label, "verstr": verstr, "raw": score,
                "row": row, "container": verstr in parents})

    def _item(self, members):
        pool = [m for m in members if not m["container"]] or members
        ranked = _ordered(pool, "raw")
        best, goal = ranked[0], None
        schema = effective_schema(self.scope.schema, self.scope.rows.declared_schema())
        found = goal_metric(schema, [m["row"] for m in ranked])
        if found:
            metric, direction = found
            valued = [m for m in ranked
                      if is_finite_number((m["row"].get("metrics") or {}).get(metric))]
            if valued:
                best = (min if direction == "min" else max)(
                    valued, key=lambda m: m["row"]["metrics"][metric])
                goal = {"metric": metric, "goal": direction,
                        "value": best["row"]["metrics"][metric]}
        return dict(best, group_size=len(members), goal=goal,
                    best=max(m["raw"] for m in members))

    def explain(self, items):
        docs = similar_fts.stored_docs(self.scope.conn, self.scope.app,
                                       [i["verstr"] for i in items])
        explainer = Explainer(self.scope.conn, self.query.doc, self.query.weights,
                              self.query.text_only, self.match)
        explainer.prepare(list(docs.values()))
        for item in items:
            doc = docs.get(item["verstr"])
            item["reasons"], item["signals"] = (
                explainer.explain(doc, item["row"], self.query.row) if doc else ([], {}))


def _ordered(items, key="score"):
    """*items* by *key* desc, then timestamp desc, then verstr and app."""
    items = sorted(items, key=lambda i: (i["verstr"], str(i["app"] or "")))
    items.sort(key=lambda i: _timestamp(i["row"]), reverse=True)
    items.sort(key=lambda i: i[key], reverse=True)
    return items


def _timestamp(row):
    stamp = row.get("timestamp")
    return stamp if isinstance(stamp, str) else ""


def similar_runs_multi(scopes, target, *, top=10, rows_filter=None, weights=None,
                       deadline=None):
    """The *top* runs most similar to *target* over *scopes* — each a
    :class:`Scope` or ``(app, snapshot, schema)``, *schema* that app's conf
    metrics schema (the runs' declared goals are merged in); *rows_filter(app,
    row)* keeps a candidate; *weights* override the default signal weights.

    Items: ``{"app", "verstr", "score", "reasons", "signals", "group_size",
    "goal": {"metric", "goal", "value"} | None, "row"}`` (``row`` a copy).
    """
    query = _Query(target, weights)
    found, searches = [], []
    for scope in map(as_scope, scopes):
        with scope.lock, deadline_guard(scope.conn, deadline):
            search = _Search(scope, query, rows_filter)
            found += search.groups(top)
            searches.append(search)
    best = max((item["best"] for item in found), default=0.0)
    items = _ordered(found, "raw")[:top]
    for search in searches:
        mine = [i for i in items if i["scope"] is search]
        if mine:
            with search.scope.lock, deadline_guard(search.scope.conn, deadline):
                search.explain(mine)
    return [{"app": i["app"], "verstr": i["verstr"],
             "score": round(i["raw"] / best, 4) if best else 0.0,
             "reasons": i["reasons"], "signals": i["signals"], "group_size": i["group_size"],
             "goal": i["goal"], "row": dict(i["row"])} for i in items]


def similar_runs(snapshot, target, *, top=10, rows_filter=None, schema=None, weights=None,
                 app=None, deadline=None):
    """:func:`similar_runs_multi` over one app's *snapshot* (or :class:`Scope`)."""
    return similar_runs_multi([(app, snapshot, schema)], target, top=top,
                              rows_filter=rows_filter, weights=weights, deadline=deadline)
