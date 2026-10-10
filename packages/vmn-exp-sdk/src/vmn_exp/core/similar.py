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
left out, with the runs of its exact code (same ``code_verstr``) and its
whole tree (:meth:`~vmn_exp.core.similar_index.SimilarIndex.root`: its outer
run, every run under it, its own inner runs) — in the target's ``app`` only,
when given.

Candidates are grouped — the runs of one tree (a sweep's outer run, its
trials and the SDK runs they open), else the runs of one ``code_verstr`` —
so a sweep or repeats of one code fill one slot, shown by the member best on
the group's goal metric (:func:`goal_metric`), else the most similar — a
container (a run with inner runs) only when the group holds nothing else;
``group_size`` counts them.
Items sort by score, then newest, then verstr. Scores are never stored:
they change with every new run. Pure: no storage.
"""
from collections import Counter

from vmn_exp.core.metric_schema import effective_schema, metric_goal
from vmn_exp.core.similar_index import index_for, run_command, side_tables
from vmn_exp.core.similar_profile import build_profile, objective_names, profile_tokens
from vmn_exp.core.similar_score import score
from vmn_exp.core.similar_text import query_weights, shared_reason
from vmn_exp.core.values import is_finite_number


def target_from_snapshot(snapshot, verstr, text=None, text_only=False):
    """The target dict of the run *verstr* of *snapshot*; KeyError when absent."""
    row = index_for(snapshot).row(verstr)
    if row is None:
        raise KeyError(verstr)
    features_of, intent_of, hypothesis_of = side_tables(snapshot)
    notes = getattr(snapshot, "create_notes", None) or {}
    return {"row": row, "features": features_of(verstr), "intent": intent_of(verstr),
            "hypothesis": hypothesis_of(verstr), "text": text, "text_only": bool(text_only),
            "command": run_command(snapshot, row), "create_note": notes.get(verstr)}


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
    def __init__(self, target):
        row = target.get("row") or {}
        self.text_only = bool(target.get("text_only"))
        self.profile = build_profile(
            row, target.get("features"), target.get("intent"), target.get("hypothesis"),
            command=target.get("command"), text=target.get("text"),
            create_note=target.get("create_note") or row.get("create_note"),
        )
        self.weights = query_weights(self.profile.terms)
        self.tokens = profile_tokens(self.profile, structured=not self.text_only)
        self.app = target.get("app")
        self.row, self.verstr, self.code = row, row.get("verstr"), row.get("code_verstr")

    def exclusion(self, index):
        """``excluded(row)``: whether *row* is the target, of its code or of
        its tree in *index*; None for a target without a verstr."""
        if not self.verstr:
            return None
        root = index.root(self.row)

        def excluded(row):
            return (row["verstr"] == self.verstr or row.get("code_verstr") == self.code
                    or index.root(row) == root)
        return excluded


class _Scope:
    """One app's candidates for a query, with their raw BM25 text scores."""

    def __init__(self, app, snapshot, schema, query, rows_filter):
        self.app, self.index = app, index_for(snapshot)
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
            for verstr in self.candidates:
                p = self.index.profile(verstr)
                if p.length:
                    self.text_raw[verstr] = self.index.bm25.score(query.weights, p.terms, p.length)

    def _text(self, query, verstr, best):
        raw = self.text_raw.get(verstr)
        if raw is None:
            return None, None
        p = self.index.profile(verstr)
        reason = shared_reason(query.profile.terms, p.terms, self.index.bm25.idf,
                               phrases=query.profile.keywords + p.keywords) if raw else None
        return (raw / best if best else 0.0), reason

    def scored(self, query, best, weights):
        """Item drafts (``app``, ``verstr``, ``score``, ``reasons``,
        ``signals``, the shared ``row``) of the candidates scoring above 0."""
        out = []
        for verstr in self.candidates:
            text, reason = self._text(query, verstr, best)
            if query.text_only:
                total, reasons, signals = text or 0.0, [reason] if reason else [], {"text": text}
            else:
                total, reasons, signals = score(
                    query.profile, self.index.profile(verstr), weights, text, reason)
            if total > 0:
                out.append({"app": self.app, "verstr": verstr, "score": round(total, 4),
                            "reasons": reasons, "row": self.index.row(verstr),
                            "signals": {k: round(v, 4) for k, v in signals.items()}})
        return out

    def items(self, query, best, weights):
        groups = {}
        for draft in self.scored(query, best, weights):
            groups.setdefault(self._group_key(draft["row"]), []).append(draft)
        return [self._item(members) for members in groups.values()]

    def _group_key(self, row):
        if self.index.in_tree(row):
            return self.index.root(row)
        return row.get("code_verstr") or row["verstr"]

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


def similar_runs_multi(scopes, target, *, top=10, rows_filter=None, weights=None):
    """The *top* runs most similar to *target* over *scopes* — ``[(app,
    snapshot, schema)]``, *schema* being that app's conf metrics schema (the
    runs' declared goals are merged in). Text scores are normalised by the
    best candidate over all scopes. *rows_filter(row)* keeps a candidate's
    snapshot row; *weights* override :data:`~vmn_exp.core.similar_score.DEFAULT_WEIGHTS`.

    Items: ``{"app", "verstr", "score", "reasons", "signals", "group_size",
    "goal": {"metric", "goal", "value"} | None, "row"}`` (``row`` a copy).
    """
    query = _Query(target)
    if not query.tokens:
        return []
    prepared = [_Scope(app, snapshot, schema, query, rows_filter)
                for app, snapshot, schema in scopes]
    best = max((raw for scope in prepared for raw in scope.text_raw.values()), default=0.0)
    items = [item for scope in prepared for item in scope.items(query, best, weights)]
    return _ordered(items)[:top]


def similar_runs(snapshot, target, *, top=10, rows_filter=None, schema=None, weights=None, app=None):
    """:func:`similar_runs_multi` over one app's *snapshot*."""
    return similar_runs_multi([(app, snapshot, schema)], target, top=top,
                              rows_filter=rows_filter, weights=weights)
