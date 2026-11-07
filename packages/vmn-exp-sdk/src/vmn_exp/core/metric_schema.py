#!/usr/bin/env python3
"""The *effective* metrics schema: the app's conf.yml plus what runs declare.

A run's ``define_metric(name, goal=..., hidden=..., chart=...)`` travels in
its log, so a store workspace without any conf.yml still knows which way a
metric sorts, which metrics to keep out of default views and how to draw them.
The effective schema is the conf schema plus, for every name the conf does not
declare, the ``hidden``/``chart`` the latest run declares (runs ordered by
creation time) and the one goal its runs declare. Runs declaring different
goals give the name no goal but ``goal_conflict: true`` (plan 32): no best, no
ranking, no verdict — and a conf goal (exact or glob) always wins
(:func:`resolve_goal`, shared with compare). Every run of the app counts,
archived ones too: the board has one schema for both of its views.

It drives sort direction, hidden columns and chart kinds only — never a
summary: run A declaring ``goal: min`` must not change which value run B
ranks on (see :func:`~vmn_exp.core.metric_summary.with_policies`, which takes
the conf schema and the run's own definitions).

Names are exact metric names or ``fnmatch`` globs; an exact name beats a glob
(:func:`~vmn_exp.core.step_metric.lookup`). Pure: no storage.
"""
from collections import Counter

from vmn_exp.core.metric_summary import GOALS
from vmn_exp.core.step_metric import lookup


def hidden_fields(hidden=None):
    """``{"hidden"?}`` for a ``define_metric`` entry; ValueError unless a bool."""
    if hidden is None:
        return {}
    if not isinstance(hidden, bool):
        raise ValueError(f"hidden must be True or False, got {hidden!r}")
    return {"hidden": hidden}


# How the ui draws a metric (plan 28 N8): a curve over the steps, the last
# value per step as bars sorted by value, or a step -> value table.
CHARTS = ("line", "bars", "table")


def chart_fields(chart=None):
    """``{"chart"?}`` for a ``define_metric`` entry; ValueError unless one of
    :data:`CHARTS`."""
    if chart is None:
        return {}
    if chart not in CHARTS:
        raise ValueError(f"chart must be one of {', '.join(CHARTS)}, got {chart!r}")
    return {"chart": chart}


def _schema_fields(definition):
    """The ``goal``/``hidden``/``chart`` of one declaration that the schema
    can carry."""
    goal, hidden, chart = _goal_of(definition), _hidden_of(definition), _chart_of(definition)
    fields = {"goal": goal} if goal else {}
    if hidden:
        fields["hidden"] = hidden[0]
    if chart:
        fields["chart"] = chart
    return fields


def declared_fields(definitions):
    """``{name: {"goal"?, "hidden"?, "chart"?}}`` of one run's folded definitions
    (:func:`~vmn_exp.core.fold.fold_definitions`); ``{}`` when none."""
    declared = {}
    for name, definition in (definitions or {}).items():
        fields = _schema_fields(definition) if isinstance(definition, dict) else {}
        if fields:
            declared[name] = fields
    return declared


def resolve_goal(conf_goal, goals):
    """A metric's one goal (plan 32): *conf_goal* (the app schema's) wins;
    else the one goal of *goals* (the goals runs declare — a list, None
    for a run without one, or a ``{goal: runs}`` count). Runs
    declaring different goals give none, ``goal_conflict`` saying so."""
    if conf_goal:
        return {"goal": conf_goal}
    distinct = set(goals) - {None}
    if len(distinct) > 1:
        return {"goal": None, "goal_conflict": True}
    return {"goal": distinct.pop() if distinct else None}


def run_goals(declared):
    """``{name: goal}`` of one run's :func:`declared_fields` (None: none)."""
    return {name: f["goal"] for name, f in (declared or {}).items() if "goal" in f}


def goal_counts(declarations):
    """``{name: {goal: runs declaring it}}`` of runs' :func:`declared_fields`."""
    counts = {}
    for declared in declarations:
        for name, goal in run_goals(declared).items():
            counts.setdefault(name, Counter())[goal] += 1
    return counts


def declared_schema(declarations, counts=None):
    """Runs' :func:`declared_fields`, oldest run first, merged per name:
    ``hidden``/``chart`` the latest run's, the goal :func:`resolve_goal`'s
    over the runs' *counts* (:func:`goal_counts` of *declarations* when
    None)."""
    declarations = list(declarations)
    merged = {}
    for declared in declarations:
        for name, fields in declared.items():
            entry = merged.setdefault(name, {})
            entry.update((k, v) for k, v in fields.items() if k != "goal")
    for name, goals in (goal_counts(declarations) if counts is None else counts).items():
        resolved = resolve_goal(None, goals)
        if resolved.get("goal_conflict"):
            merged[name]["goal_conflict"] = True
        elif resolved["goal"]:
            merged[name]["goal"] = resolved["goal"]
    return merged


def effective_schema(conf, declared):
    """*conf* (the app's metrics schema) plus the *declared* names it lacks;
    a goal *conf* gives a declared name through a glob wins over the runs'."""
    if not declared:
        return conf or {}
    if not conf:
        return declared
    out = {**declared, **conf}
    with_goal = {pattern: entry for pattern, entry in conf.items() if _goal_of(entry)}
    if not with_goal:
        return out
    for name in declared.keys() - conf.keys():
        goal = metric_goal(with_goal, name)
        if goal:
            fields = {k: v for k, v in declared[name].items() if k != "goal_conflict"}
            out[name] = {**fields, "goal": goal}
    return out


def with_goal_counts(schema, counts):
    """*schema* with ``goals`` (*counts*' ``{goal: runs}``) on each entry
    whose runs declare different goals — the payload says why it has none."""
    return {name: {**entry, "goals": dict(counts.get(name) or {})}
            if entry.get("goal_conflict") else entry for name, entry in schema.items()}


def _goal_of(definition):
    goal = (definition or {}).get("goal")
    return goal if goal in GOALS else None


_CONFLICT = "conflict"


def _goal_or_conflict(definition):
    return _CONFLICT if (definition or {}).get("goal_conflict") else _goal_of(definition)


def metric_goal(schema, metric):
    """``"min"``/``"max"`` the *schema* gives *metric* (exact name, else the
    latest matching glob), or None — also when that entry's runs declare
    different goals (no other glob stands in)."""
    goal = lookup(metric, schema or {}, _goal_or_conflict)
    return None if goal == _CONFLICT else goal


def with_resolved_goals(schema, names):
    """*schema* plus, on each of *names* without its own goal, the goal a glob
    gives it — so a reader of exact names needs no glob matching."""
    out = dict(schema or {})
    for name in names:
        goal = metric_goal(schema, name)
        if goal and not _goal_of(out.get(name)):
            out[name] = {**(out.get(name) or {}), "goal": goal}
    return out


def higher_is_better(goal):
    """A *goal*'s direction: True for ``max``, False for ``min``, None
    without one (no guessed direction, plan 32)."""
    return None if goal is None else goal == "max"


def _hidden_of(definition):
    hidden = (definition or {}).get("hidden")
    return (hidden,) if isinstance(hidden, bool) else None


def is_hidden(metric, run_defs=None, schema=None):
    """Whether *metric* is hidden: the run's own declaration, else *schema*'s."""
    for declarations in (run_defs or {}, schema or {}):
        found = lookup(metric, declarations, _hidden_of)
        if found:
            return found[0]
    return False


def hidden_metrics(names, run_defs=None, schema=None):
    """The sorted *names* that are hidden (see :func:`is_hidden`)."""
    return sorted(n for n in set(names) if is_hidden(n, run_defs, schema))


def _chart_of(definition):
    chart = (definition or {}).get("chart")
    return chart if chart in CHARTS else None


def metric_charts(names, run_defs=None, schema=None):
    """``{name: chart}`` of the *names* not drawn as a line: the run's own
    declaration, else *schema*'s (exact name beats a glob)."""
    charts = {}
    for name in sorted(set(names)):
        chart = lookup(name, run_defs or {}, _chart_of) or lookup(name, schema or {}, _chart_of)
        if chart and chart != "line":
            charts[name] = chart
    return charts
