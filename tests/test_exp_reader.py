"""The programmatic read side of the experiment SDK: version_stamp.exp.reader."""
import datetime
import itertools
import json
import os

import pytest
import yaml
from helpers import _storage

from version_stamp.exp.reader import get_run, list_runs


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ago(seconds):
    now = datetime.datetime.now(datetime.timezone.utc)
    return _iso(now - datetime.timedelta(seconds=seconds))


def _exp_dir(app_layout, verstr):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    return path


_SECOND = itertools.count(1)  # experiments are written one second apart


def _write_experiment(
    app_layout, verstr, run_state=None, parent=None, log=None, timestamp=None, note=None
):
    """Fixture setup: an experiment dir as ``vmn exp`` would leave it on disk."""
    path = _exp_dir(app_layout, verstr)
    meta = {
        "verstr": verstr,
        "code_verstr": verstr,
        "timestamp": timestamp or f"2026-09-21T12:00:{next(_SECOND):02d}",
        "note": note if note is not None else f"note-{verstr}",
        "branch": "master",
        "base_version": "0.0.1",
    }
    if parent:
        meta["parent"] = parent
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f, sort_keys=True)
    if run_state is not None:
        with open(os.path.join(path, "run_state.yml"), "w") as f:
            yaml.dump(run_state, f, sort_keys=False)
    for entry in log or []:
        _append_log(app_layout, verstr, entry)
    return path


def _append_log(app_layout, verstr, entry, writer="w0"):
    path = os.path.join(_exp_dir(app_layout, verstr), f"log.{writer}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _metrics_entry(ts, values, step=None):
    return {"timestamp": ts, "type": "metrics", "values": values, "step": step}


def _running_state():
    return {
        "state": "running",
        "command": ["python", "train.py"],
        "pid": 4242,
        "host": "somebox",
        "started_at": _ago(120),
        "heartbeat": _ago(5),
        "heartbeat_interval_sec": 30,
        "exit_code": None,
        "finished_at": None,
        "duration_sec": None,
    }


def _stuck_state():
    state = _running_state()
    state["heartbeat"] = _ago(3600)
    return state


def _finished_state(exit_code):
    return {
        "state": "finished",
        "command": ["python", "train.py"],
        "pid": 4242,
        "host": "somebox",
        "started_at": _ago(600),
        "heartbeat": _ago(300),
        "heartbeat_interval_sec": 30,
        "exit_code": exit_code,
        "finished_at": _ago(300),
        "duration_sec": 300.0,
    }


def _seed_all_statuses(app_layout):
    _write_experiment(app_layout, "0.0.1", run_state=None)
    _write_experiment(app_layout, "0.0.2", run_state=_running_state())
    _write_experiment(app_layout, "0.0.3", run_state=_stuck_state())
    _write_experiment(app_layout, "0.0.4", run_state=_finished_state(0))
    _write_experiment(app_layout, "0.0.5", run_state=_finished_state(7))
    return {
        "0.0.1": "created",
        "0.0.2": "running",
        "0.0.3": "stuck",
        "0.0.4": "succeeded",
        "0.0.5": "failed",
    }


def _runs(app_layout, **kwargs):
    return list_runs(app_layout.app_name, storage=_storage(app_layout), **kwargs)


# ---------------------------------------------------------------------------
# list_runs: statuses
# ---------------------------------------------------------------------------


def test_list_runs_reports_every_status(app_layout):
    expected = _seed_all_statuses(app_layout)
    rows = _runs(app_layout)
    assert {r["verstr"]: r["status"] for r in rows} == expected


def test_list_runs_row_carries_params_verbatim(app_layout):
    _write_experiment(
        app_layout,
        "0.0.1",
        log=[
            {
                "timestamp": "2026-09-21T12:00:00Z",
                "type": "create",
                "params": {"lr": 0.01, "model": "xgb", "cache": True},
            }
        ],
    )
    row = _runs(app_layout)[0]
    assert row["params"] == {"lr": 0.01, "model": "xgb", "cache": True}


def test_get_run_carries_params_verbatim(app_layout):
    _write_experiment(
        app_layout,
        "0.0.1",
        log=[
            {
                "timestamp": "2026-09-21T12:00:00Z",
                "type": "create",
                "params": {"model": "xgb", "cache": False},
            }
        ],
    )
    run = get_run(app_layout.app_name, "0.0.1", storage=_storage(app_layout))
    assert run["params"] == {"model": "xgb", "cache": False}


def test_row_carries_metadata_metrics_and_status_fields(app_layout):
    _write_experiment(
        app_layout,
        "0.0.1",
        run_state=_running_state(),
        timestamp="2026-09-21T12:00:01",
        log=[_metrics_entry("2026-09-21T12:05:00Z", {"loss": 0.25})],
    )
    row = _runs(app_layout)[0]

    assert row["verstr"] == "0.0.1"
    assert row["timestamp"] == "2026-09-21T12:00:01"
    assert row["note"] == "note-0.0.1"
    assert row["branch"] == "master"
    assert row["base_version"] == "0.0.1"
    assert row["parent"] is None
    assert row["metrics"] == {"loss": 0.25}

    assert row["status"] == "running"
    for key in (
        "exit_code",
        "started_at",
        "finished_at",
        "heartbeat",
        "duration_sec",
        "pid",
        "host",
        "command",
        "stale_sec",
        "heartbeat_interval_sec",
    ):
        assert key in row, key
    assert row["pid"] == 4242
    assert row["host"] == "somebox"
    assert row["command"] == ["python", "train.py"]

    assert row["children"] == []
    assert row["kind"] == "single"
    assert row["depth"] == 0
    assert row["tree_status"] == "running"


def test_stale_heartbeat_reports_stuck(app_layout):
    state = _running_state()
    state.pop("exit_code")
    state["heartbeat"] = _ago(600)
    _write_experiment(app_layout, "0.0.1", run_state=state)

    row = _runs(app_layout)[0]
    assert row["status"] == "stuck"
    assert row["stale_sec"] >= 600


def test_missing_run_state_reports_created(app_layout):
    _write_experiment(app_layout, "0.0.1")
    row = _runs(app_layout)[0]
    assert row["status"] == "created"
    assert row["exit_code"] is None


def test_status_is_derived_on_every_call(app_layout, monkeypatch):
    """A running run whose heartbeat goes stale must report stuck next call."""
    import version_stamp.core.experiment_status as status_mod

    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    assert _runs(app_layout)[0]["status"] == "running"

    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or later)
    assert _runs(app_layout)[0]["status"] == "stuck"
    assert get_run(app_layout.app_name, "0.0.1", storage=_storage(app_layout))[
        "status"
    ] == "stuck"


# ---------------------------------------------------------------------------
# nesting
# ---------------------------------------------------------------------------


def test_nesting_reports_children_kind_depth_and_parent(app_layout):
    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    _write_experiment(
        app_layout, "0.0.2", run_state=_finished_state(0), parent="0.0.1"
    )
    by_verstr = {r["verstr"]: r for r in _runs(app_layout)}

    outer = by_verstr["0.0.1"]
    assert outer["kind"] == "outer"
    assert outer["children"] == ["0.0.2"]
    assert outer["depth"] == 0
    assert outer["parent"] is None

    inner = by_verstr["0.0.2"]
    assert inner["kind"] == "inner"
    assert inner["parent"] == "0.0.1"
    assert inner["depth"] == 1
    assert inner["children"] == []


def test_outer_tree_status_reports_failed_child(app_layout):
    _write_experiment(app_layout, "0.0.1", run_state=_finished_state(0))
    _write_experiment(
        app_layout, "0.0.2", run_state=_finished_state(0), parent="0.0.1"
    )
    _write_experiment(
        app_layout, "0.0.3", run_state=_finished_state(1), parent="0.0.1"
    )

    outer = next(r for r in _runs(app_layout) if r["verstr"] == "0.0.1")
    assert outer["status"] == "succeeded"
    assert outer["tree_status"] == "failed"
    assert sorted(outer["children"]) == ["0.0.2", "0.0.3"]

    detail = get_run(app_layout.app_name, "0.0.1", storage=_storage(app_layout))
    assert detail["tree_status"] == "failed"
    assert sorted(detail["children"]) == ["0.0.2", "0.0.3"]


# ---------------------------------------------------------------------------
# filtering / ordering
# ---------------------------------------------------------------------------


def test_status_filter_accepts_a_string_or_a_list(app_layout):
    _seed_all_statuses(app_layout)

    rows = _runs(app_layout, status="running,stuck")
    assert sorted(r["verstr"] for r in rows) == ["0.0.2", "0.0.3"]

    rows = _runs(app_layout, status=["failed"])
    assert [r["verstr"] for r in rows] == ["0.0.5"]

    assert _runs(app_layout, status="bogus") == []
    assert len(_runs(app_layout, status=None)) == 5


def _seed_for_queries(app_layout):
    """Five runs carrying statuses, metrics and params the query language reads."""
    expected = _seed_all_statuses(app_layout)
    for verstr, loss, params in (
        ("0.0.1", 0.9, {"model": "xgb"}),
        ("0.0.2", 0.1, {"model": "xgb", "cache": True}),
        ("0.0.3", 0.4, {"model": "linear"}),
        ("0.0.4", 0.2, {"model": "linear"}),
        ("0.0.5", 2.0, {}),
    ):
        _append_log(
            app_layout,
            verstr,
            {"timestamp": "2026-09-21T12:00:00Z", "type": "create", "params": params},
        )
        _append_log(app_layout, verstr, _metrics_entry("2026-09-21T12:05:00Z", {"loss": loss}))
    return expected


def test_query_filters_on_metrics_and_params(app_layout):
    _seed_for_queries(app_layout)

    rows = _runs(app_layout, query="metrics.loss < 0.5")
    assert sorted(r["verstr"] for r in rows) == ["0.0.2", "0.0.3", "0.0.4"]

    rows = _runs(app_layout, query='params.model = "xgb"')
    assert sorted(r["verstr"] for r in rows) == ["0.0.1", "0.0.2"]

    rows = _runs(app_layout, query="params.cache = true")
    assert [r["verstr"] for r in rows] == ["0.0.2"]

    assert len(_runs(app_layout, query=None)) == 5


def test_query_composes_with_the_status_filter(app_layout):
    _seed_for_queries(app_layout)

    rows = _runs(app_layout, query="metrics.loss < 0.5", status="succeeded,failed")
    assert sorted(r["verstr"] for r in rows) == ["0.0.4"]

    rows = _runs(app_layout, query='status in ("failed", "created")')
    assert sorted(r["verstr"] for r in rows) == ["0.0.1", "0.0.5"]


def test_query_filters_before_last_and_sort(app_layout):
    _seed_for_queries(app_layout)

    rows = _runs(app_layout, query="metrics.loss < 0.5", last=2, sort="loss")
    assert [r["verstr"] for r in rows] == ["0.0.4", "0.0.3"]


def test_query_error_propagates_to_the_caller(app_layout):
    from version_stamp.core.experiment_query import QueryError

    _seed_for_queries(app_layout)
    with pytest.raises(QueryError) as excinfo:
        _runs(app_layout, query="metrics.loss <")
    assert "at offset" in str(excinfo.value)

    with pytest.raises(QueryError):
        _runs(app_layout, query="bogus_field = 1")


def test_last_keeps_the_most_recent_rows(app_layout):
    _seed_all_statuses(app_layout)
    rows = _runs(app_layout, last=2)
    assert [r["verstr"] for r in rows] == ["0.0.4", "0.0.5"]


def test_sort_orders_by_a_metric(app_layout):
    for verstr, loss in (("0.0.1", 0.5), ("0.0.2", 0.1), ("0.0.3", 0.9)):
        _write_experiment(
            app_layout,
            verstr,
            log=[_metrics_entry("2026-09-21T12:05:00Z", {"loss": loss})],
        )
    rows = _runs(app_layout, sort="loss")
    assert [r["verstr"] for r in rows] == ["0.0.2", "0.0.1", "0.0.3"]


# ---------------------------------------------------------------------------
# get_run
# ---------------------------------------------------------------------------


def test_get_run_returns_log_series_and_artifacts(app_layout):
    _write_experiment(
        app_layout,
        "0.0.1",
        run_state=_finished_state(0),
        log=[
            {"timestamp": "2026-09-21T12:00:00Z", "type": "create", "note": "hello"},
            _metrics_entry("2026-09-21T12:01:00Z", {"loss": 0.5}, step=1),
            _metrics_entry("2026-09-21T12:02:00Z", {"loss": 0.2}, step=2),
        ],
    )
    art_dir = os.path.join(_exp_dir(app_layout, "0.0.1"), "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    with open(os.path.join(art_dir, "model.bin"), "w") as f:
        f.write("weights")

    run = get_run(app_layout.app_name, "0.0.1", storage=_storage(app_layout))

    assert [e["type"] for e in run["log"]] == ["create", "metrics", "metrics"]
    assert run["metrics"] == {"loss": 0.2}
    assert run["series"]["loss"] == [
        {"step": 1, "ts": "2026-09-21T12:01:00Z", "value": 0.5},
        {"step": 2, "ts": "2026-09-21T12:02:00Z", "value": 0.2},
    ]
    assert run["artifacts"] == [{"name": "model.bin", "size": len("weights")}]
    assert run["status"] == "succeeded"
    assert run["verstr"] == "0.0.1"


def _count_reads(monkeypatch):
    """Count the per-experiment file reads get_run/list_runs perform."""
    from version_stamp.exp import reader

    counts = {"run_state": 0, "log": 0}
    real_state, real_log = reader.load_run_state, reader._load_log

    def counting_state(storage, app_name, verstr):
        counts["run_state"] += 1
        return real_state(storage, app_name, verstr)

    def counting_log(storage, app_name, verstr):
        counts["log"] += 1
        return real_log(storage, app_name, verstr)

    monkeypatch.setattr(reader, "load_run_state", counting_state)
    monkeypatch.setattr(reader, "_load_log", counting_log)
    return counts


def _seed_two_trees(app_layout):
    """Six experiments: a 3-run subtree under 'outer', and 3 unrelated runs."""
    _write_experiment(app_layout, "0.0.1", run_state=_finished_state(0))
    _write_experiment(app_layout, "0.0.2", run_state=_running_state())
    outer = "0.0.3"
    _write_experiment(app_layout, outer, run_state=_running_state())
    _write_experiment(
        app_layout, "0.0.4", parent=outer, run_state=_finished_state(0)
    )
    _write_experiment(app_layout, "0.0.5", parent=outer, run_state=_finished_state(9))
    _write_experiment(app_layout, "0.0.6", run_state=_finished_state(0))
    return outer


def test_get_run_reads_only_the_runs_subtree(app_layout, monkeypatch):
    outer = _seed_two_trees(app_layout)
    counts = _count_reads(monkeypatch)

    run = get_run(app_layout.app_name, outer, storage=_storage(app_layout))

    assert sorted(run["children"]) == ["0.0.4", "0.0.5"]
    assert run["kind"] == "outer"
    assert run["status"] == "running"
    assert run["tree_status"] == "failed"  # a failed child is the headline
    assert run["idx"] == 3

    assert counts["log"] == 1, "only the run's own log is needed"
    assert counts["run_state"] == 3, "the subtree only: outer + its two children"


def test_list_runs_still_reads_the_whole_workspace(app_layout, monkeypatch):
    _seed_two_trees(app_layout)
    counts = _count_reads(monkeypatch)

    rows = list_runs(app_layout.app_name, storage=_storage(app_layout))

    assert len(rows) == 6
    assert counts["run_state"] == 6
    assert counts["log"] == 6


def test_get_run_with_no_artifacts(app_layout):
    _write_experiment(app_layout, "0.0.1")
    run = get_run(app_layout.app_name, "0.0.1", storage=_storage(app_layout))
    assert run["artifacts"] == []
    assert run["log"] == []
    assert run["series"] == {}


def test_get_run_resolves_latest_index_and_prefix(app_layout):
    _write_experiment(
        app_layout, "0.0.1-dev.aaaa1111", timestamp="2026-09-21T12:00:01"
    )
    _write_experiment(
        app_layout, "0.0.2-dev.bbbb2222", timestamp="2026-09-21T12:00:02"
    )

    storage = _storage(app_layout)
    assert get_run(app_layout.app_name, storage=storage)["verstr"] == "0.0.2-dev.bbbb2222"
    assert (
        get_run(app_layout.app_name, "latest", storage=storage)["verstr"]
        == "0.0.2-dev.bbbb2222"
    )
    assert (
        get_run(app_layout.app_name, "@1", storage=storage)["verstr"]
        == "0.0.1-dev.aaaa1111"
    )
    assert (
        get_run(app_layout.app_name, "0.0.2-dev.bbbb", storage=storage)["verstr"]
        == "0.0.2-dev.bbbb2222"
    )
    assert (
        get_run(app_layout.app_name, "0.0.1-dev.aaaa1111", storage=storage)["verstr"]
        == "0.0.1-dev.aaaa1111"
    )


def test_get_run_raises_on_an_unknown_ref(app_layout):
    _write_experiment(app_layout, "0.0.1-dev.aaaa1111")
    with pytest.raises(ValueError):
        get_run(
            app_layout.app_name, "0.0.9-dev.nope0000", storage=_storage(app_layout)
        )


# ---------------------------------------------------------------------------
# resolution from the current repo
# ---------------------------------------------------------------------------


def test_app_name_and_storage_default_to_the_current_repo(app_layout, monkeypatch):
    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    monkeypatch.setenv("VMN_WORKING_DIR", app_layout.repo_path)
    monkeypatch.setenv("VMN_APP_NAME", app_layout.app_name)

    rows = list_runs()
    assert [r["verstr"] for r in rows] == ["0.0.1"]
    assert get_run()["verstr"] == "0.0.1"


def test_a_sole_app_with_experiments_needs_no_app_name(app_layout, monkeypatch):
    _write_experiment(app_layout, "0.0.1")
    monkeypatch.setenv("VMN_WORKING_DIR", app_layout.repo_path)
    monkeypatch.delenv("VMN_APP_NAME", raising=False)

    assert [r["verstr"] for r in list_runs()] == ["0.0.1"]
