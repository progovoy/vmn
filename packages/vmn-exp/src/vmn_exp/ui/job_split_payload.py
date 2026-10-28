#!/usr/bin/env python3
"""A job's split (plan 28 P3) as JSON, from the
:class:`~vmn_exp.ui.job_split.SplitTallies` parts its subtree is split into.

A value is named only when no part may hold some of its runs under
``other`` (a part whose ``other`` holds runs may hold any key past its
:meth:`~vmn_exp.ui.job_split.SplitTallies.cut`: a value is named up to the
lowest cut), so a named value's numbers
are always its whole subtree's. The :data:`~vmn_exp.ui.job_split.MAX_VALUES`
largest named values are listed, most runs first (ties: by key); the rest
are one ``other`` entry, last.
"""
from vmn_exp.ui.job_rollup_payload import count_fields, duration_fields
from vmn_exp.ui.job_split import MAX_VALUES
from vmn_exp.ui.leaderboard_group_clause import field as query_field
from vmn_exp.ui.leaderboard_group_clause import literal, value_clause
from vmn_exp.ui.leaderboard_group_fields import NONE, NONE_LABEL, key_text

OTHER_LABEL = "other"


def _entry(tallies):
    return {**count_fields(tallies), "duration": duration_fields([t.duration for t in tallies])}


def _other_clause(field, named):
    """``field not in (...)`` of the named values (and present, when the
    no-value one is named); None when one has no literal."""
    name = query_field(field)
    texts = [literal(value) for key, value in named if key != NONE]
    if name is None or None in texts:
        return None
    clause = f"{name} not in ({', '.join(texts)})" if texts else None
    if any(key == NONE for key, _ in named):
        clause = f"{clause} and {name} != null" if clause else f"{name} != null"
    return clause


def split_payload(parts, spec):
    """``[{key, label, clause, total, counts, done, ..., duration}]`` of the
    job whose subtree's parts are *parts*, ``other`` (``key`` None) last."""
    named = {}
    for part in parts:
        for key, tally in part.named.items():
            named.setdefault(key, []).append(tally)
    lowest = min((cut for cut in (p.cut() for p in parts) if cut is not None), default=None)
    exact = {k: tallies for k, tallies in named.items() if lowest is None or k <= lowest}
    totals = {k: sum(t.total for t in tallies) for k, tallies in exact.items()}
    listed = sorted(exact, key=lambda k: (-totals[k], k))[:MAX_VALUES]
    out = [dict(key=k, label=NONE_LABEL if k == NONE else key_text(k),
                clause=value_clause(spec.field, k, exact[k][0].value), **_entry(exact[k]))
           for k in listed]
    shown = set(listed)
    rest = [t for k, tallies in named.items() if k not in shown for t in tallies]
    rest += [p.other for p in parts if p.other.counts]
    if rest:
        values = [(k, exact[k][0].value) for k in listed]
        out.append(dict(key=None, label=OTHER_LABEL, other=True,
                        clause=_other_clause(spec.field, values), **_entry(rest)))
    return out
