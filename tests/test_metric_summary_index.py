"""Summary policies through the experiment index and the reader API.

The index folds each record once; the app's metrics schema only decides which
of the folded last/min/max a row shows, so a schema change re-derives the rows
without re-reading any log, and a grown log keeps its summaries right.
"""
import json
import os

import yaml
from helpers import _storage

from vmn_exp.core.index import indexed_status_rows
from vmn_exp.sdk.reader import get_run, list_runs

GOAL_MIN = {"loss": {"goal": "min"}}


def _exp_dir(app_layout, verstr):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    return path


def _write(app_layout, verstr, losses, second):
    path = _exp_dir(app_layout, verstr)
    meta = {"verstr": verstr, "code_verstr": verstr,
            "timestamp": f"2026-09-21T12:00:{second:02d}"}
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    _append(app_layout, verstr, losses)


def _append(app_layout, verstr, losses, start=0):
    with open(os.path.join(_exp_dir(app_layout, verstr), "log.w0.jsonl"), "a") as f:
        for i, loss in enumerate(losses, start):
            f.write(json.dumps({"timestamp": f"2026-09-21T12:05:{i:02d}Z",
                                "type": "metrics", "step": i,
                                "values": {"loss": loss}}) + "\n")


def _write_conf(app_layout, metrics):
    path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    with open(path, "w") as f:
        yaml.dump({"conf": {"experiment": {"metrics": metrics}}}, f)


def _seed(app_layout):
    _write(app_layout, "0.0.1", [1.0, 0.2, 0.9], 1)  # overfit: best 0.2, last 0.9
    _write(app_layout, "0.0.2", [0.8, 0.5], 2)  # steady: best 0.5, last 0.5


def _losses(rows):
    return {r["verstr"]: r["metrics"]["loss"] for r in rows}


def _indexed(app_layout, schema):
    rows, _, _ = indexed_status_rows(_storage(app_layout), app_layout.app_name,
                                     schema=schema)
    return rows


def test_index_rows_follow_the_schema(app_layout):
    _seed(app_layout)
    assert _losses(_indexed(app_layout, GOAL_MIN)) == {"0.0.1": 0.2, "0.0.2": 0.5}
    assert _losses(_indexed(app_layout, {})) == {"0.0.1": 0.9, "0.0.2": 0.5}
    assert _losses(_indexed(app_layout, GOAL_MIN)) == {"0.0.1": 0.2, "0.0.2": 0.5}


def test_index_incremental_refresh_keeps_summaries_right(app_layout):
    _seed(app_layout)
    _indexed(app_layout, GOAL_MIN)
    _append(app_layout, "0.0.2", [0.1, 0.7], start=2)
    rows = _indexed(app_layout, GOAL_MIN)
    assert _losses(rows) == {"0.0.1": 0.2, "0.0.2": 0.1}
    summary = next(r for r in rows if r["verstr"] == "0.0.2")["metric_summary"]["loss"]
    assert summary == {"last": 0.7, "min": 0.1, "max": 0.8}


def test_list_runs_ranks_on_the_conf_goal(app_layout):
    _seed(app_layout)
    _write_conf(app_layout, GOAL_MIN)
    rows = list_runs(app_layout.app_name, sort="loss")
    assert [r["verstr"] for r in rows] == ["0.0.1", "0.0.2"]
    assert [r["verstr"] for r in list_runs(app_layout.app_name,
                                           query="metrics.loss < 0.3")] == ["0.0.1"]
    assert [r["verstr"] for r in list_runs(app_layout.app_name, use_index=False,
                                           query="metrics.loss < 0.3")] == ["0.0.1"]


def test_conf_summary_last_overrides_the_goal(app_layout):
    _seed(app_layout)
    _write_conf(app_layout, {"loss": {"goal": "min", "summary": "last"}})
    rows = list_runs(app_layout.app_name, sort="loss")
    assert [r["verstr"] for r in rows] == ["0.0.2", "0.0.1"]


def test_get_run_carries_the_summary(app_layout):
    _seed(app_layout)
    _write_conf(app_layout, GOAL_MIN)
    run = get_run(app_layout.app_name, "@1")
    assert run["metrics"]["loss"] == 0.2
    assert run["metric_summary"]["loss"] == {"last": 0.9, "min": 0.2, "max": 1.0}
