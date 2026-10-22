#!/usr/bin/env python3
"""What a remote cold load reads of a record before publishing its row.

The newest records of a store are often its stuck runs (the latest launch),
each with a log and a metric segment per sync: hundreds of GETs a run. Their
rows come first from metadata.yml, run_state.yml and each log stream's first
object (where the run's ``create``/params entries are); the rest of the log
and an unfinished run's metric segments fold afterwards, into the same row,
as the log and metric files having grown (:mod:`index_logs`).

A finished run's streams are one object each (a compacted log, a ``.vmx``):
nothing is cut, it loads whole in one go.
"""
from vmn_exp.core.logfiles import group_log_names
from vmn_exp.core.metric_files import group_metric_names, is_metric_file


def first_objects(names):
    """*names* (``{filename: signature}``) cut to what a row needs first, or
    None when nothing would be cut."""
    later = set()
    for group in group_log_names(names).values():
        later.update(group[1:])
    metric_groups = group_metric_names(n for n in names if is_metric_file(n)).values()
    if any(len(group) > 1 for group in metric_groups):
        later.update(n for n in names if is_metric_file(n))
    if not later:
        return None
    return {name: sig for name, sig in names.items() if name not in later}
