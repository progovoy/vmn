#!/usr/bin/env python3
"""How far each child of an outer run got, for its fleet table (plan 20 B6).

A child's ``last_step`` is ``{"step", "of"}`` as a failed run's detail gives
it (:func:`~vmn_exp.ui.readers.failure_context.last_step`), read through the
run page's parsed-log cache. Only a local record is read: there a poll costs
one listing per child and the new lines, where a remote store would re-read
every grown child log on each poll. Elsewhere, and for a child that logged no
step, it is None.
"""
from vmn_exp.ui.readers.failure_context import last_step
from vmn_exp.ui.readers.parsed_logs import _local


def add_child_steps(fleet, storage, app_name, parsed, read_log):
    """Set ``last_step`` on each child of *fleet* (a fleet summary or None);
    *parsed* is the :class:`~vmn_exp.ui.readers.parsed_logs.ParsedLogs` cache."""
    local = _local(storage) is not None
    for child in (fleet or {}).get("children", ()):
        snapshot = parsed.get(storage, app_name, child["verstr"], read_log) if local else None
        child["last_step"] = last_step(snapshot, child.get("params")) if snapshot else None
