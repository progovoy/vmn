#!/usr/bin/env python3
"""The runs a run page compares a run against (plan 20 D7, K3, K4).

All answered from an app's index snapshot (rows in storage order, run
states), so nothing here reads storage or git: ``base`` (the run itself, when
it captured a patch), its ``parent``/``forked_from``/``rerun_of``, the
``previous`` run of its branch and command, the app's ``best`` run on the
primary declared goal, and the ``last_good`` run a failure card links to.
"""
from vmn_exp.core.log import primary_metric
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.status import derive_status
from vmn_exp.core.values import is_finite_number

ORIGINS = ("parent", "forked_from", "rerun_of")
_GLOB = frozenset("*?[")


def status_of(snapshot, verstr):
    return derive_status(
        snapshot.run_states.get(verstr),
        observed_at=snapshot.run_state_observed_at.get(verstr),
    )


def run_ref(row):
    return {"verstr": row["verstr"], "idx": row.get("idx"), "name": row.get("name")}


def _with_status(snapshot, row):
    return dict(run_ref(row), status=status_of(snapshot, row["verstr"]))


def _command(snapshot, verstr):
    return (snapshot.run_states.get(verstr) or {}).get("command")


def _earlier_rows(snapshot, row):
    """The unarchived rows stored before *row*, newest first."""
    rows = snapshot.rows
    pos = (row.get("idx") or 0) - 1
    if not (0 <= pos < len(rows) and rows[pos] is row):
        pos = next(i for i, r in enumerate(rows) if r is row)
    return (r for r in reversed(rows[:pos]) if not r.get("archived"))


def previous_run(snapshot, row):
    """The latest earlier row of *row*'s branch and command, or None."""
    command = _command(snapshot, row["verstr"])
    return next(
        (r for r in _earlier_rows(snapshot, row)
         if r.get("branch") == row.get("branch") and _command(snapshot, r["verstr"]) == command),
        None,
    )


def last_good(snapshot, verstr):
    """``{verstr, idx, name}`` of the latest earlier succeeded run of
    *verstr*'s command, or None (also for a run the snapshot lacks)."""
    row = snapshot.row(verstr)
    if row is None:
        return None
    command = _command(snapshot, verstr)
    found = next(
        (r for r in _earlier_rows(snapshot, row)
         if _command(snapshot, r["verstr"]) == command
         and status_of(snapshot, r["verstr"]) == "succeeded"),
        None,
    )
    return run_ref(found) if found else None


def primary_goal(schema):
    """The metric the schema marks primary when it has a goal, else the
    first exactly named metric with one; None without a declared goal."""
    primary = primary_metric(schema)
    if primary and metric_goal(schema, primary):
        return primary
    return next(
        (name for name, spec in (schema or {}).items()
         if not _GLOB & set(name) and metric_goal({name: spec}, name)),
        None,
    )


def best_run(ordered, metric, verstr):
    """The first row of *ordered* (best first) other than *verstr* that
    carries a finite *metric*, or None."""
    return next(
        (r for r in ordered
         if r["verstr"] != verstr and is_finite_number((r.get("metrics") or {}).get(metric))),
        None,
    )


def baselines(snapshot, verstr, has_patch, schema, ordered_by):
    """K3's ``{base?, parent?, forked_from?, rerun_of?, previous?, best?}``,
    each ``{verstr, idx, name, status}``; *ordered_by(metric)* is the app's
    rows best first on *metric*, asked only when *schema* declares a goal."""
    row = snapshot.row(verstr)
    found = {"base": row if has_patch else None}
    for origin in ORIGINS:
        found[origin] = snapshot.row(row.get(origin)) if row.get(origin) else None
    found["previous"] = previous_run(snapshot, row)
    metric = primary_goal(schema)
    found["best"] = best_run(ordered_by(metric), metric, verstr) if metric else None
    return {k: _with_status(snapshot, r) for k, r in found.items() if r is not None}
