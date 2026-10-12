#!/usr/bin/env python3
"""Similar runs: "has anyone run something like this before?"

:func:`similar_runs` scores a snapshot's candidate runs
(:mod:`vmn_exp.core.similar_index`) against a *target* —

    {"row": row | None, "features": dict | None, "intent": dict | None,
     "hypothesis": str | None, "text": str | None, "text_only": bool,
     "command": argv?, "create_note": str?, "app": str?}

a run (:func:`target_from_snapshot`) or a working tree (a row-like dict
without a verstr, or None). ``text`` replaces the target's text document
(``--context``); ``text_only`` scores that text alone. The target run is
left out, with its whole tree (:meth:`~vmn_exp.core.similar_index.SimilarIndex.root`:
its outer run, every run under it, its own inner runs) and its reruns — the
runs of its rerun identity (:func:`~vmn_exp.core.similar_profile.rerun_key`:
same ``code_verstr``, params and inputs) but a fork of it or the run it
forked from, a continuation — in the target's ``app`` only, when given. Runs
of its code with other params or inputs are candidates like any other.

Candidates are grouped — the runs of one tree (a sweep's outer run, its
trials and the SDK runs they open), else the runs of one rerun identity —
so a sweep or the reruns of one config fill one slot, shown by the member best on
the group's goal metric (:func:`goal_metric`), else the most similar — a
container (a run with inner runs) only when the group holds nothing else;
``group_size`` counts them.
Items sort by score, then newest, then verstr. Scores are never stored:
they change with every new run. A *deadline* (a :func:`time.monotonic`
value) bounds the work: past it, building the index or scoring raises
:class:`SimilarDeadlineExceeded`. Pure: no storage.
"""
from collections import Counter

from vmn_exp.core.metric_schema import effective_schema, metric_goal
from vmn_exp.core.similar_index import (  # noqa: F401  (SimilarDeadlineExceeded: re-exported)
    SimilarDeadlineExceeded,
    check_deadline,
    index_for,
    run_facts,
)
from vmn_exp.core.similar_profile import build_profile, objective_names, profile_tokens
from vmn_exp.core.similar_score import Target, score
from vmn_exp.core.similar_text import query_weights, shared_reason
from vmn_exp.core.values import is_finite_number


def target_from_snapshot(snapshot, verstr, text=None, text_only=False, *, app=None):
    """The target dict of the run *verstr* of *snapshot*; KeyError when absent.
    *app* names the snapshot's app, so that over several apps
    (:func:`similar_runs_multi`) the target's exclusions apply in its own only."""
    row = _row_of(snapshot, verstr)
    if row is None:
        raise KeyError(verstr)
    features, intent, hypothesis, command, note = run_facts(snapshot)(row)
    target = {"row": row, "features": features, "intent": intent, "hypothesis": hypothesis,
              "text": text, "text_only": bool(text_only), "command": command,
              "create_note": note}
    if app is not None:
        target["app"] = app
    return target


def _row_of(snapshot, verstr):
    """*snapshot*'s row of *verstr*, or None — without building its index."""
    lookup = getattr(snapshot, "row", None)
    if callable(lookup):
        return lookup(verstr)
    return next((row for row in snapshot.rows if row["verstr"] == verstr), None)


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
    """A target, read once: its profile, BM25 query weights, tokens and —
    unless the text alone is scored — its score :class:`Target` under *weights*."""

    def __init__(self, target, weights=None):
        row = target.get("row") or {}
        self.text_only = bool(target.get("text_only"))
        self.profile = build_profile(
            row, target.get("features"), target.get("intent"), target.get("hypothesis"),
            command=target.get("command"), text=target.get("text"),
            create_note=target.get("create_note") or row.get("create_note"),
        )
        self.weights = query_weights(self.profile.terms)
        self.score_target = None if self.text_only else Target(self.profile, weights)
        self.tokens = profile_tokens(self.profile, structured=not self.text_only)
        self.app = target.get("app")
        self.row, self.verstr, self.rerun = row, row.get("verstr"), self.profile.rerun

    def exclusion(self, index):
        """``excluded(row)``: whether *row* is the target, of its tree in
        *index* or a rerun of it (:func:`~vmn_exp.core.similar_profile.rerun_key`)
        that is no fork of it nor its fork source; None for a target without a verstr."""
        if not self.verstr:
            return None
        root = index.root(self.row)

        def excluded(row):
            verstr = row["verstr"]
            if verstr == self.verstr or index.root(row) == root:
                return True
            return (self.rerun is not None and index.profile(verstr).rerun == self.rerun
                    and not self._forked_with(row))
        return excluded

    def _forked_with(self, row):
        """Whether *row* is a fork of the target or the run it forked from."""
        return (row.get("forked_from") == self.verstr
                or self.row.get("forked_from") == row["verstr"])


class _Scope:
    """One app's candidates for a query, with their raw BM25 text scores.
    Candidates are ranked on their scores alone; :meth:`reasons` explains
    the few returned."""

    def __init__(self, app, snapshot, schema, query, rows_filter, deadline=None):
        self.index = index_for(snapshot, deadline, structured=not query.text_only)
        self.app, self._deadline = app, deadline
        declared = getattr(snapshot, "declared_schema", None)
        self.schema = effective_schema(schema, declared() if declared else {})
        excluded = query.exclusion(self.index) if query.app in (None, app) else None

        def keep(verstr):
            row = self.index.row(verstr)
            return (not (excluded and excluded(row))
                    and (rows_filter is None or rows_filter(row)))

        self.candidates = self.index.candidates(query.tokens, keep=keep)
        self.text_raw = {}
        if query.weights:
            bm25 = self.index.bm25
            idfs = bm25.idfs(query.weights)
            for done, verstr in enumerate(self.candidates):
                check_deadline(deadline, done)
                p = self.index.profile(verstr)
                if p.length:
                    self.text_raw[verstr] = bm25.score(query.weights, p.terms, p.length, idfs)

    def _text(self, verstr, best):
        raw = self.text_raw.get(verstr)
        return None if raw is None else (raw / best if best else 0.0)

    def _text_reason(self, query, verstr):
        if not self.text_raw.get(verstr):
            return None
        p = self.index.profile(verstr)
        return shared_reason(query.profile.terms, p.terms, self.index.bm25.idf,
                             phrases=query.profile.keywords + p.keywords)

    def scored(self, query, best):
        """Item drafts (``app``, ``verstr``, ``score``, ``reasons`` — empty
        until :meth:`reasons` —, ``signals``, the shared ``row``) of the
        candidates scoring above 0."""
        out = []
        for done, verstr in enumerate(self.candidates):
            check_deadline(self._deadline, done)
            text = self._text(verstr, best)
            if query.text_only:
                total, signals = text or 0.0, {"text": text}
            else:
                total, _, signals = score(query.score_target, self.index.profile(verstr),
                                          text_score=text, why=False)
            if total > 0:
                out.append({"app": self.app, "verstr": verstr, "score": round(total, 4),
                            "reasons": [], "row": self.index.row(verstr),
                            "signals": {k: round(v, 4) for k, v in signals.items()}})
        return out

    def reasons(self, query, verstr, best):
        """The reasons of candidate *verstr*'s score."""
        reason = self._text_reason(query, verstr)
        if query.text_only:
            return [reason] if reason else []
        return score(query.score_target, self.index.profile(verstr),
                     text_score=self._text(verstr, best), text_reason=reason)[1]

    def items(self, query, best):
        groups = {}
        for draft in self.scored(query, best):
            groups.setdefault(self._group_key(draft["row"]), []).append(draft)
        return [self._item(members) for members in groups.values()]

    def _group_key(self, row):
        if self.index.in_tree(row):
            return "tree", self.index.root(row)
        rerun = self.index.profile(row["verstr"]).rerun
        return ("rerun", rerun) if rerun else ("run", row["verstr"])

    def _item(self, members):
        # A container (a run with inner runs) stands in only when the group holds nothing else.
        pool = [m for m in members if m["verstr"] not in self.index.parents] or members
        ranked = _ordered(pool)
        best, goal = ranked[0], None
        found = goal_metric(self.schema, [m["row"] for m in ranked])
        if found:
            metric, direction = found

            def value(item):
                return (item["row"].get("metrics") or {}).get(metric)

            valued = [m for m in ranked if is_finite_number(value(m))]
            if valued:
                best = (min if direction == "min" else max)(valued, key=value)
                goal = {"metric": metric, "goal": direction, "value": value(best)}
        return dict(best, group_size=len(members), goal=goal, row=dict(best["row"]))


def _ordered(items):
    """*items* by score desc, then timestamp desc, then verstr and app."""
    items = sorted(items, key=lambda i: (i["verstr"], i["app"] or ""))
    items.sort(key=lambda i: _timestamp(i["row"]), reverse=True)
    items.sort(key=lambda i: i["score"], reverse=True)
    return items


def _timestamp(row):
    stamp = row.get("timestamp")
    return stamp if isinstance(stamp, str) else ""


def similar_runs_multi(scopes, target, *, top=10, rows_filter=None, weights=None,
                       deadline=None):
    """The *top* runs most similar to *target* over *scopes* — ``[(app,
    snapshot, schema)]``, *schema* being that app's conf metrics schema (the
    runs' declared goals are merged in). Text scores are normalised by the
    best candidate over all scopes. *rows_filter(row)* keeps a candidate's
    snapshot row; *weights* override :data:`~vmn_exp.core.similar_score.DEFAULT_WEIGHTS`.
    Raises :class:`SimilarDeadlineExceeded` once past a *deadline*.

    Items: ``{"app", "verstr", "score", "reasons", "signals", "group_size",
    "goal": {"metric", "goal", "value"} | None, "row"}`` (``row`` a copy).
    """
    query = _Query(target, weights)
    if not query.tokens:
        return []
    prepared = [_Scope(app, snapshot, schema, query, rows_filter, deadline)
                for app, snapshot, schema in scopes]
    best = max((raw for scope in prepared for raw in scope.text_raw.values()), default=0.0)
    found = [(scope, item) for scope in prepared for item in scope.items(query, best)]
    scope_of = {id(item): scope for scope, item in found}
    items = _ordered([item for _, item in found])[:top]
    for item in items:
        item["reasons"] = scope_of[id(item)].reasons(query, item["verstr"], best)
    return items


def similar_runs(snapshot, target, *, top=10, rows_filter=None, schema=None, weights=None, app=None,
                 deadline=None):
    """:func:`similar_runs_multi` over one app's *snapshot*."""
    return similar_runs_multi([(app, snapshot, schema)], target, top=top,
                              rows_filter=rows_filter, weights=weights, deadline=deadline)
