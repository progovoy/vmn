#!/usr/bin/env python3
"""What :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache` answers
over a whole filtered set rather than a page: parameter importance and the
facets (plan 23 S2: within a scope and the filters too)."""
from vmn_exp.core.importance import param_importance
from vmn_exp.ui.leaderboard_scope import Filters, check_scope
from vmn_exp.ui.leaderboard_top_counts import top_counts
from vmn_exp.ui.readers.experiments import facets as facets_of

# Importance results kept (each pins its scored runs' params dicts).
IMPORTANCE_RESULTS = 8


class SetAnswers:
    """Mixed into the cache: needs its ``_base``, ``schema_key`` and the
    ``_importance``/``_facets``/``_filtered_facets``/``_top_counts`` memos."""

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
        key = (self.schema_key(schema), metric, tuple((v, m, id(p)) for v, m, p in scored))
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
        base, bucket = self._base(snapshot)
        check_scope(base, scope)
        f = Filters(None, status, query, None, archived, scope)
        return self._filtered_facets.get(
            (base.token, bucket) + f, lambda: facets_of(base.tail(bucket, 0, f)))

    def top_counts(self, snapshot, archived=False, scope=None, query=None, status=None):
        """``{"jobs", "singles"}``: the top-level runs with and without
        children (plan 23 S7) among the rows :meth:`facets` reads."""
        if scope is None and not query and not status:
            return self._top_counts.get(snapshot, bool(archived))
        base, bucket = self._base(snapshot)
        check_scope(base, scope)
        f = Filters(None, status, query, None, archived, scope)
        return self._filtered_facets.get(
            ("top", base.token, bucket) + f, lambda: top_counts(base.tail(bucket, 0, f)))
