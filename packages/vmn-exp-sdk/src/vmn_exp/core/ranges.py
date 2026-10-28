#!/usr/bin/env python3
"""A run's marked step ranges: the ``range`` log entry and its view.

``run.mark_range(name, start_step, end_step)`` appends ``{"type": "range",
"name", "start_step", "end_step"}`` (an SWA window, a warm-up); the run page
shades each as an x band on all of the run's charts (plan 28 N5). The entry
has no ``step``, so it is never rewound. Readers serve::

    {"ranges": [{"name", "start_step", "end_step"}], "ranges_total": n}

``ranges`` holds the first :data:`MAX_RANGES` distinct ranges in log order;
``ranges_total`` counts them all.

Pure: no storage, no clock (beyond the new entry's timestamp).
"""
from vmn_exp._base import now_iso

RANGE = "range"
MAX_RANGES = 100


def _step(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def create_range_entry(name, start_step, end_step):
    """The log entry marking steps *start_step*..*end_step* as *name*;
    ValueError for a non-numeric step or a start past the end."""
    start, end = _step(start_step), _step(end_step)
    if start is None or end is None:
        raise ValueError("mark_range: start_step and end_step must be numbers")
    if start > end:
        raise ValueError(f"mark_range: start_step {start} is past end_step {end}")
    return {"timestamp": now_iso(), "type": RANGE, "name": str(name),
            "start_step": start, "end_step": end}


def _range_of(entry):
    """``(name, start, end)`` of a well-formed ``range`` entry, else None."""
    if not isinstance(entry, dict) or entry.get("type") != RANGE:
        return None
    name, start, end = entry.get("name"), _step(entry.get("start_step")), _step(entry.get("end_step"))
    if not isinstance(name, str) or start is None or end is None or start > end:
        return None
    return name, start, end


class RangeIndex:
    """The ranges of a growing log, extended entry by entry."""

    def __init__(self):
        self._seen = set()
        self._kept = []

    def add(self, entries):
        """Fold *entries* in; whether the view changed."""
        changed = False
        for entry in entries:
            found = _range_of(entry)
            if found is None or found in self._seen:
                continue
            self._seen.add(found)
            if len(self._kept) < MAX_RANGES:
                self._kept.append(found)
            changed = True
        return changed

    def extend(self, entries):
        self.add(entries)
        return self

    def view(self):
        return {
            "ranges": [{"name": n, "start_step": s, "end_step": e} for n, s, e in self._kept],
            "ranges_total": len(self._seen),
        }


def ranges_view(log):
    """The ranges view of a whole *log*."""
    return RangeIndex().extend(log).view()
