#!/usr/bin/env python3
"""Experiment diff for the vmn ui API: metric delta + real tree diff text."""
from types import SimpleNamespace

from version_stamp.cli.experiment import _get_latest_metrics, _load_log
from version_stamp.cli.snapshot import _resolve_verstr, render_tree_diff
from version_stamp.ui.readers.experiments import experiment_storage


def experiment_diff(root_path, app_name, ref1, ref2):
    """Compare two experiments. Returns (result, error_message_or_None)."""
    storage = experiment_storage(root_path)

    resolved = []
    for ref in (ref1, ref2):
        verstr, err = _resolve_verstr(storage, app_name, ref, kind="experiment")
        if err:
            return None, err
        resolved.append(verstr)
    v1, v2 = resolved

    sides = []
    for verstr in (v1, v2):
        meta, patches = storage.load(app_name, verstr)
        if meta is None:
            return None, f"Experiment {verstr} not found"
        log = _load_log(storage, app_name, verstr)
        sides.append((meta, patches, _get_latest_metrics(log)))
    (meta1, patches1, m1), (meta2, patches2, m2) = sides

    metrics_delta = {
        key: {"from": m1.get(key), "to": m2.get(key)}
        for key in sorted(set(m1) | set(m2))
        if m1.get(key) != m2.get(key)
    }

    # Materialization only needs a root path (both sides have base_commit).
    vcs_stub = SimpleNamespace(vmn_root_path=root_path, name=app_name)
    diff_text, err = render_tree_diff(
        vcs_stub, v1, meta1, patches1, v2, meta2, patches2
    )
    if err:
        return None, err

    return {
        "from_verstr": v1,
        "to_verstr": v2,
        "metrics_delta": metrics_delta,
        "diff": diff_text,
    }, None
