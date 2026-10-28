#!/usr/bin/env python3
"""A run's declared progress (plan 28 P2): the metrics ``progress`` and
``progress_total`` it logs on itself (``run.set_progress``; other names by
an app's ``experiment.ui.progress`` mapping), which an outer run's rollup
reads before its run counts."""
from collections import namedtuple

from vmn_exp.core.values import is_finite_number

DONE, TOTAL, UNIT = "progress", "progress_total", "progress_unit"

ProgressNames = namedtuple("ProgressNames", "done total unit")
DEFAULT_NAMES = ProgressNames(DONE, TOTAL, None)


def progress_names(mapping=None):
    """The names an ``experiment.ui.progress`` *mapping* (``{done, total,
    unit}``, *unit* a label) gives, the defaults where it says nothing."""
    mapping = mapping if isinstance(mapping, dict) else {}

    def pick(key, default):
        value = mapping.get(key)
        return value if isinstance(value, str) and value else default

    return ProgressNames(pick("done", DONE), pick("total", TOTAL), pick("unit", None))


def _unit(row, names):
    if names.unit:
        return names.unit
    unit = (row.get("params") or {}).get(UNIT)
    return unit if isinstance(unit, str) and unit else None


def declared_progress(row, names=DEFAULT_NAMES):
    """``(done, total, unit)`` from *row*'s own metrics, None unless both
    are finite and the total is positive."""
    metrics = row.get("metrics") or {}
    done, total = metrics.get(names.done), metrics.get(names.total)
    if not (is_finite_number(done) and is_finite_number(total)) or total <= 0:
        return None
    return done, total, _unit(row, names)
