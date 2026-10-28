#!/usr/bin/env python3
"""What :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache` answers
over a whole filtered set rather than a page: parameter importance and the
facets (plan 23 S2: within a scope and the filters too; there, also the
top note signatures, plan 28 N7)."""
from collections import Counter

from vmn_exp.core.importance import param_importance
from vmn_exp.ui.leaderboard_scope import Filters, check_scope, scope_positions
from vmn_exp.ui.leaderboard_top_counts import top_counts
from vmn_exp.ui.readers.experiments import facets as facets_of

# Importance results kept (each pins its scored runs' params dicts).
IMPORTANCE_RESULTS = 8
NO_TOP_RUNS = {"jobs": 0, "singles": 0}
# A job's importance is scored again per this share of its runs scored.
IMPORTANCE_STEP = 0.05
# Note signatures a filtered facets answer lists.
TOP_NOTE_SIGS = 20


def note_facet(rows, notes_of):
    """``[{sig, runs, count}]``: the :data:`TOP_NOTE_SIGS` note signatures
    most of *rows* logged (then most notes, then by name), from
    ``notes_of(verstr)`` (plan 28 N7)."""
    runs, counts = Counter(), Counter()
    for row in rows:
        for sig, held in (notes_of(row["verstr"]) or {}).items():
            runs[sig] += 1
            counts[sig] += held.get("count") or 0
    top = sorted(runs, key=lambda sig: (-runs[sig], -counts[sig], sig))[:TOP_NOTE_SIGS]
    return [{"sig": sig, "runs": runs[sig], "count": counts[sig]} for sig in top]


def _importance_step(base, scope):
    """How many more scored runs of *scope* score its importance again."""
    return max(1, round(len(scope_positions(base, scope)) * IMPORTANCE_STEP))


class SetAnswers:
    """Mixed into the cache: needs its ``_base``, ``schema_key`` and the
    ``_importance``/``_facets``/``_filtered_facets``/``_top_counts``/
    ``_status_counts`` memos."""

    def importance(self, snapshot, schema, metric, status=None, query=None, archived=False,
                   scope=None):
        """Parameter importance for *metric* over the filtered rows.

        Memoized on what is scored — each scored run's verstr, metric value
        and params — so a new generation or status bucket that changed none
        of them (a live run still without the metric) costs a filter, not a
        forest. Raises ``ValueError`` when no visible run carries *metric*,
        ``QueryError`` on a bad *query*. Keyed by *schema* too: the rows'
        metric values follow it.
        """
        base, bucket = self._base(snapshot)
        check_scope(base, scope)
        f = Filters(status=status, query=query, archived=archived, scope=scope)
        rows = base.tail(bucket, 0, f)
        scored = tuple(
            (row["verstr"], row["metrics"].get(metric), row.get("params"))
            for row in rows if metric in row["metrics"]
        )
        if scope is None:
            what = tuple((v, m, id(p)) for v, m, p in scored)
        else:
            what = (snapshot.app_name, f, len(scored) // _importance_step(base, scope))
        key = (self.schema_key(schema), metric, what)
        universe = lambda: base.tail(bucket, 0, Filters(archived=archived))  # noqa: E731
        # The value keeps the params dicts alive, so their ids stay unique.
        return self._importance.get(
            key, lambda: (scored, param_importance(rows, metric, universe=universe()))
        )[1]

    def facets(self, snapshot, archived=False, scope=None, query=None, status=None):
        """The app's filter vocabulary, once per snapshot (archived rows only
        when *archived*), moved on from the app's last counts; over the rows
        of *scope* passing *query* and *status*, once per time bucket (no
        order needed: storage order)."""
        if scope is None and not query and not status:
            return self._facets.get(snapshot, archived)
        return self._filtered(snapshot, archived, scope, query, status)[0]

    def top_counts(self, snapshot, archived=False, scope=None, query=None, status=None):
        """``{"jobs", "singles"}``: the top-level runs with and without
        children (plan 23 S7) among the rows :meth:`facets` reads."""
        if scope is None and not query and not status:
            return self._top_counts.get(snapshot, bool(archived))
        return self._filtered(snapshot, archived, scope, query, status)[1]

    def status_summary(self, snapshot, now):
        """:func:`~vmn_exp.ui.status_summary.status_summary` of the visible
        rows as of *now*, carried across generations
        (:mod:`~vmn_exp.ui.status_counts`)."""
        return self._status_counts.summary(snapshot, now)

    def facets_payload(self, snapshot, **where):
        """What ``experiments-facets`` answers: :meth:`facets` with
        :meth:`top_counts`, from one walk of the filtered rows."""
        return dict(self.facets(snapshot, **where), **self.top_counts(snapshot, **where))

    def _filtered(self, snapshot, archived, scope, query, status):
        """``(facets, top counts)`` of the filtered rows, once per time
        bucket; a scope's subtree has no top-level run to count."""
        base, bucket = self._base(snapshot)
        check_scope(base, scope)
        f = Filters(None, status, query, None, archived, scope)

        def both():
            rows = base.tail(bucket, 0, f)
            found, sigs = facets_of(rows), note_facet(rows, base.snapshot.notes_of)
            if sigs:
                found["note_sigs"] = sigs
            return found, (NO_TOP_RUNS if scope else top_counts(rows))

        return self._filtered_facets.get((base.token, bucket) + f, both)
