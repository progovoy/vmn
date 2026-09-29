"""The metrics schema is a read parameter of the experiment index, not state.

Each caller's rows follow the schema it passes: another caller's schema never
leaks in, and asking with a different schema neither re-derives the shared
rows nor bumps the generation (which would churn every ETag).
"""
import json
import os

import yaml
from helpers import _storage

from vmn_exp.core import index as experiment_index
from vmn_exp.core.index import indexed_snapshot, indexed_status_rows

GOAL_MIN = {"loss": {"goal": "min"}}
GOAL_MAX = {"loss": {"goal": "max"}}


def _write(app_layout, verstr, losses, second):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    meta = {"verstr": verstr, "code_verstr": verstr,
            "timestamp": f"2026-09-21T12:00:{second:02d}"}
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    with open(os.path.join(path, "log.w0.jsonl"), "w") as f:
        for i, loss in enumerate(losses):
            f.write(json.dumps({"timestamp": f"2026-09-21T12:05:{i:02d}Z",
                                "type": "metrics", "step": i,
                                "values": {"loss": loss}}) + "\n")


def _seed(app_layout):
    _write(app_layout, "0.0.1", [1.0, 0.2, 0.9], 1)
    _write(app_layout, "0.0.2", [0.5], 2)
    return _storage(app_layout), app_layout.app_name


def _losses(rows):
    return {r["verstr"]: r["metrics"]["loss"] for r in rows}


def test_callers_with_different_schemas_each_see_their_own_values(app_layout):
    storage, app = _seed(app_layout)
    for _ in range(2):  # interleaved, so none inherits another's schema
        assert _losses(indexed_status_rows(storage, app, schema=GOAL_MIN)[0])[
            "0.0.1"] == 0.2
        assert _losses(indexed_snapshot(storage, app, wait=True).rows)["0.0.1"] == 0.9
        assert _losses(indexed_status_rows(storage, app, schema=GOAL_MAX)[0])[
            "0.0.1"] == 1.0
        assert _losses(indexed_status_rows(storage, app)[0])["0.0.1"] == 0.9


def test_a_schema_view_leaves_the_shared_snapshot_alone(app_layout):
    storage, app = _seed(app_layout)
    base = indexed_snapshot(storage, app, wait=True)
    view = base.summarized(GOAL_MIN)
    assert view.row("0.0.1")["metrics"]["loss"] == 0.2
    assert base.row("0.0.1")["metrics"]["loss"] == 0.9
    assert base.summarized(GOAL_MIN) is view  # memoized per snapshot
    assert base.summarized(None) is base
    again = indexed_snapshot(storage, app, wait=True, schema=GOAL_MAX)
    assert again.generation == base.generation
    index = experiment_index.shared_index(storage, app)
    assert index.snapshot() is base


def test_a_schema_that_changes_nothing_returns_the_snapshot_itself(app_layout):
    storage, app = _seed(app_layout)
    base = indexed_snapshot(storage, app, wait=True)
    assert base.summarized({"acc": {"goal": "max"}}) is base


def test_unchanged_rows_keep_their_view_row_across_generations(app_layout):
    storage, app = _seed(app_layout)
    first = indexed_snapshot(storage, app, wait=True, schema=GOAL_MIN)
    _write(app_layout, "0.0.3", [0.7, 0.3], 3)
    second = indexed_snapshot(storage, app, wait=True, schema=GOAL_MIN)
    assert second.generation > first.generation
    assert second.row("0.0.1") is first.row("0.0.1")
    assert second.row("0.0.3")["metrics"]["loss"] == 0.3


def test_snapshot_rows_leave_metric_summary_to_the_row_copies(app_layout):
    storage, app = _seed(app_layout)
    snap = indexed_snapshot(storage, app, wait=True)
    assert all("metric_summary" not in row for row in snap.rows)
    rows = {r["verstr"]: r for r in indexed_status_rows(storage, app)[0]}
    assert rows["0.0.1"]["metric_summary"] == {
        "loss": {"last": 0.9, "min": 0.2, "max": 1.0}}
    assert rows["0.0.2"]["metric_summary"] == {}
    assert snap.metric_summary("0.0.1") == rows["0.0.1"]["metric_summary"]


def test_the_direct_fallback_follows_the_same_rules(app_layout, monkeypatch):
    storage, app = _seed(app_layout)

    def broken(*args, **kwargs):
        raise RuntimeError("no index")

    monkeypatch.setattr(experiment_index, "shared_index", broken)
    snap = indexed_snapshot(storage, app, schema=GOAL_MIN)
    assert snap.row("0.0.1")["metrics"]["loss"] == 0.2
    assert "metric_summary" not in snap.row("0.0.1")
    assert _losses(indexed_snapshot(storage, app).rows)["0.0.1"] == 0.9
