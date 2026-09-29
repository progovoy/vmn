#!/usr/bin/env python3
"""The *effective* metrics schema: the app's conf.yml plus what runs declare.

A run's ``define_metric(name, goal=..., hidden=...)`` travels in its log, so a
store workspace without any conf.yml still knows which way a metric sorts and
which metrics to keep out of default views. The effective schema is the conf
schema plus, for every name the conf does not declare, the ``goal``/``hidden``
the latest run declares (runs ordered by creation time).

It drives sort direction and hidden columns only — never a summary: run A
declaring ``goal: min`` must not change which value run B ranks on (see
:func:`~vmn_exp.core.metric_summary.with_policies`, which takes the conf
schema and the run's own definitions).

Names are exact metric names or ``fnmatch`` globs; an exact name beats a glob
(:func:`~vmn_exp.core.step_metric.lookup`). Pure: no storage.
"""
from vmn_exp.core.metric_summary import GOALS
from vmn_exp.core.step_metric import lookup


def hidden_fields(hidden=None):
    """``{"hidden"?}`` for a ``define_metric`` entry; ValueError unless a bool."""
    if hidden is None:
        return {}
    if not isinstance(hidden, bool):
        raise ValueError(f"hidden must be True or False, got {hidden!r}")
    return {"hidden": hidden}


def _schema_fields(definition):
    """The ``goal``/``hidden`` of one declaration that the schema can carry."""
    goal, hidden = _goal_of(definition), _hidden_of(definition)
    fields = {"goal": goal} if goal else {}
    if hidden:
        fields["hidden"] = hidden[0]
    return fields


def declared_fields(definitions):
    """``{name: {"goal"?, "hidden"?}}`` of one run's folded definitions
    (:func:`~vmn_exp.core.fold.fold_definitions`); ``{}`` when none."""
    declared = {}
    for name, definition in (definitions or {}).items():
        fields = _schema_fields(definition) if isinstance(definition, dict) else {}
        if fields:
            declared[name] = fields
    return declared


def declared_schema(declarations):
    """Runs' :func:`declared_fields`, oldest run first, merged per name and
    field: the latest run's declaration wins."""
    merged = {}
    for declared in declarations:
        for name, fields in declared.items():
            merged.setdefault(name, {}).update(fields)
    return merged


def effective_schema(conf, declared):
    """*conf* (the app's metrics schema) plus the *declared* names it lacks."""
    if not declared:
        return conf or {}
    return {**declared, **(conf or {})}


def _goal_of(definition):
    goal = (definition or {}).get("goal")
    return goal if goal in GOALS else None


def metric_goal(schema, metric):
    """``"min"``/``"max"`` the *schema* gives *metric* (exact name, else the
    latest matching glob), or None."""
    return lookup(metric, schema or {}, _goal_of)


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
