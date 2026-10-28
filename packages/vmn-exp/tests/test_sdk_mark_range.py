"""Plan 28 N5: ``run.mark_range(name, start_step, end_step)`` logs a ``range``
entry (an SWA window, a warm-up), which readers and the run detail serve so
the run page shades it as an x band on every chart."""
import json
import os

import pytest
import yaml
from exp_helpers import _bootstrap, _storage
from fastapi.testclient import TestClient
from vmn_exp.core.ranges import MAX_RANGES, ranges_view
from vmn_exp.sdk import start_run
from vmn_exp.sdk.ranks import NoOpRun

API = "/api/v1/workspaces/main/apps"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID", "VMN_MODE"):
        monkeypatch.delenv(key, raising=False)


def _ranges(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return [e for e in log if e.get("type") == "range"]


def test_mark_range_logs_a_range_entry_and_takes_no_step(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, system_metrics=False) as run:
        run.mark_range("swa", 100, 200)
        assert run.step == 0
    [entry] = _ranges(app_layout, run.id)
    assert (entry["name"], entry["start_step"], entry["end_step"]) == ("swa", 100, 200)
    assert "step" not in entry


@pytest.mark.parametrize("start, end", [(5, 4), ("a", 4), (1, None), (True, 2)])
def test_mark_range_refuses_a_bad_range(app_layout, start, end):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, system_metrics=False) as run:
        with pytest.raises(ValueError):
            run.mark_range("swa", start, end)
    assert _ranges(app_layout, run.id) == []


def test_get_run_serves_the_ranges(app_layout):
    from vmn_exp.sdk.reader import get_run

    _bootstrap(app_layout)
    with start_run(app_layout.app_name, system_metrics=False) as run:
        run.mark_range("warmup", 0, 10)
        run.mark_range("swa", 100, 200.5)
    row = get_run(app_layout.app_name, run.id, storage=_storage(app_layout))
    assert row["ranges"] == [{"name": "warmup", "start_step": 0, "end_step": 10},
                             {"name": "swa", "start_step": 100, "end_step": 200.5}]
    assert row["ranges_total"] == 2


def test_a_noop_run_takes_mark_range_and_records_nothing():
    assert NoOpRun("app").mark_range("swa", 1, 2) is None


def test_the_view_keeps_the_first_ranges_and_counts_the_rest():
    log = [{"type": "range", "name": f"r{i}", "start_step": i, "end_step": i + 1}
           for i in range(MAX_RANGES + 5)]
    log.append({"type": "range", "name": "r0", "start_step": 0, "end_step": 1})  # repeated
    view = ranges_view(log)
    assert len(view["ranges"]) == MAX_RANGES
    assert view["ranges"][0] == {"name": "r0", "start_step": 0, "end_step": 1}
    assert view["ranges_total"] == MAX_RANGES + 5


def test_the_view_skips_malformed_entries():
    log = [{"type": "range", "name": "x", "start_step": 3, "end_step": 1},
           {"type": "range", "start_step": 1, "end_step": 2},
           {"type": "range", "name": "ok", "start_step": 1, "end_step": 2}]
    assert ranges_view(log)["ranges"] == [{"name": "ok", "start_step": 1, "end_step": 2}]


def _record(app_layout, verstr, entries):
    path = os.path.join(app_layout.repo_path, ".vmn", "store", "runs", app_layout.app_name, verstr)
    os.makedirs(os.path.join(path, "log"), exist_ok=True)
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump({"format_version": 1, "verstr": verstr, "code_verstr": verstr,
                   "branch": "master", "timestamp": "2026-09-27T10:00:00Z",
                   "base_version": "0.0.1"}, f)
    with open(os.path.join(path, "log", "w0.jsonl"), "a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_run_detail_carries_the_ranges_bounded(app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    ranges = [{"type": "range", "timestamp": "2026-09-27T10:00:01Z", "name": f"r{i}",
               "start_step": i, "end_step": i + 2} for i in range(MAX_RANGES + 1)]
    _record(app_layout, "0.0.1-exp.1", ranges)
    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    client = TestClient(create_app(manager, use_index=False))
    detail = client.get(f"{API}/{app_layout.app_name}/experiments/0.0.1-exp.1").json()
    assert detail["ranges"][0] == {"name": "r0", "start_step": 0, "end_step": 2}
    assert len(detail["ranges"]) == MAX_RANGES
    assert detail["ranges_total"] == MAX_RANGES + 1
