#!/usr/bin/env python3
"""Rows and machine-readable payloads for ``vmn exp list`` / ``vmn exp show``.

A list row is exactly what ``version_stamp.exp.reader.list_runs`` returns: the
index row, its derived status fields and its place in the run tree. ``show
--json`` adds the run's metadata, patch sizes and (the tail of) its log.
Non-finite metrics are written as ``null`` so the output is strict JSON.
"""
import json
import math

from version_stamp.core.experiment_log import experiment_row
from version_stamp.core.experiment_status import status_fields
from version_stamp.core.experiment_tree import annotate_tree

PATCH_TYPES = ("working_tree", "local_commits")


def annotated_rows(rows, run_states, observed_at=None):
    """*rows* with status and tree fields; the tree spans all of them.
    *observed_at* is ``{verstr: run_state.yml store write time}``."""
    observed_at = observed_at or {}
    return annotate_tree([
        dict(row, **status_fields(
            run_states.get(row["verstr"]), observed_at=observed_at.get(row["verstr"])
        ))
        for row in rows
    ])


def patch_lines(patches):
    """``{patch type: line count}`` for the patches present."""
    return {p: patches[p].count("\n") for p in PATCH_TYPES if (patches or {}).get(p)}


def show_payload(
    idx, metadata, patches, log, run_state, tree, log_tail=None, observed_at=None
):
    """The ``show --json`` object; *log_tail* keeps only the newest entries."""
    run = experiment_row(idx, metadata, log)
    run.update(status_fields(run_state, observed_at=observed_at))
    run.update(tree)
    run["base_commit"] = metadata.get("base_commit")
    run["has_dep_patches"] = bool(metadata.get("has_dep_patches"))
    run["patches"] = patch_lines(patches)
    run["log"] = log[-log_tail:] if log_tail else log
    run["log_total"] = len(log)
    return run


def _finite_or_none(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite_or_none(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_or_none(v) for v in value]
    return value


def dumps(payload):
    """Strict, stable JSON: sorted keys, NaN/inf as ``null``."""
    return json.dumps(
        _finite_or_none(payload), indent=2, sort_keys=True, allow_nan=False, default=str
    )
