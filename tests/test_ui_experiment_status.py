"""Run status + nesting on the experiments read side (ui readers, index, API)."""
import datetime
import json
import os

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

API = "/api/v1/workspaces/main/apps"


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


def _write_experiment(
    app_layout, verstr, run_state=None, parent=None, metrics=None, timestamp=None
):
    """Fixture setup: an experiment dir as `vmn exp` would leave it on disk."""
    path = _exp_dir(app_layout, verstr)
    meta = {
        "verstr": verstr,
        "code_verstr": verstr,
        "timestamp": timestamp or f"2026-09-21T12:00:{int(verstr[-1]):02d}",
        "note": f"note-{verstr}",
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
    for ts, values in metrics or []:
        _append_metrics(app_layout, verstr, ts, values)
    return path


def _append_metrics(app_layout, verstr, ts, values, writer="w0"):
    path = os.path.join(_exp_dir(app_layout, verstr), f"log.{writer}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps({"timestamp": ts, "type": "metrics", "values": values}) + "\n")


def _running_state():
    return {
        "state": "running",
        "command": ["python", "train.py"],
        "pid": 12345,
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
        "pid": 12345,
        "host": "somebox",
        "started_at": _ago(600),
        "heartbeat": _ago(300),
        "heartbeat_interval_sec": 30,
        "exit_code": exit_code,
        "finished_at": _ago(300),
        "duration_sec": 300.0,
    }


def _client(app_layout, use_index=True):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager, use_index=use_index))


def _index(app_layout):
    from version_stamp.ui.index import WorkspaceIndex

    return WorkspaceIndex(
        app_layout.repo_path, db_dir=os.path.join(app_layout.base_dir, "ui_index")
    )


def _seed_all_statuses(app_layout):
    _write_experiment(app_layout, "0.0.1", run_state=None)
    _write_experiment(app_layout, "0.0.2", run_state=_running_state())
    _write_experiment(app_layout, "0.0.3", run_state=_stuck_state())
    _write_experiment(app_layout, "0.0.4", run_state=_finished_state(0))
    _write_experiment(app_layout, "0.0.5", run_state=_finished_state(3))
    return {
        "0.0.1": "created",
        "0.0.2": "running",
        "0.0.3": "stuck",
        "0.0.4": "succeeded",
        "0.0.5": "failed",
    }


def test_list_endpoint_reports_every_status(app_layout):
    expected = _seed_all_statuses(app_layout)
    client = _client(app_layout)

    rows = client.get(f"{API}/{app_layout.app_name}/experiments").json()
    assert {r["verstr"]: r["status"] for r in rows} == expected


def test_list_row_carries_full_status_payload(app_layout):
    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    rows = _client(app_layout).get(f"{API}/{app_layout.app_name}/experiments").json()

    row = rows[0]
    for key in (
        "status",
        "exit_code",
        "started_at",
        "finished_at",
        "heartbeat",
        "duration_sec",
        "pid",
        "host",
        "command",
        "stale_sec",
        "parent",
        "children",
        "kind",
        "depth",
        "tree_status",
        "last_metric_at",
    ):
        assert key in row, key
    assert row["pid"] == 12345
    assert row["host"] == "somebox"
    assert row["command"] == ["python", "train.py"]
    assert row["kind"] == "single"
    assert row["depth"] == 0
    assert row["children"] == []
    assert row["tree_status"] == "running"
    assert "run_state" not in row  # raw input, replaced by the derived fields


def test_detail_endpoint_reports_status_and_keeps_existing_keys(app_layout):
    expected = _seed_all_statuses(app_layout)
    client = _client(app_layout)

    for verstr, status in expected.items():
        detail = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr}").json()
        for key in ("metadata", "log", "metrics", "series", "artifacts", "patches"):
            assert key in detail, key
        assert detail["status"]["status"] == status
        for key in ("parent", "children", "kind", "depth", "tree_status",
                    "last_metric_at", "exit_code", "pid", "host", "command",
                    "started_at", "finished_at", "heartbeat", "duration_sec",
                    "stale_sec"):
            assert key in detail["status"], key


def test_stale_heartbeat_without_exit_code_is_stuck(app_layout):
    state = _running_state()
    state.pop("exit_code")
    state["heartbeat"] = _ago(600)
    _write_experiment(app_layout, "0.0.1", run_state=state)

    rows = _client(app_layout).get(f"{API}/{app_layout.app_name}/experiments").json()
    assert rows[0]["status"] == "stuck"
    assert rows[0]["stale_sec"] >= 600


def test_missing_run_state_is_created(app_layout):
    _write_experiment(app_layout, "0.0.1")
    rows = _client(app_layout).get(f"{API}/{app_layout.app_name}/experiments").json()
    assert rows[0]["status"] == "created"
    assert rows[0]["exit_code"] is None


def test_nesting_outer_and_inner(app_layout):
    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    _write_experiment(
        app_layout, "0.0.2", run_state=_finished_state(0), parent="0.0.1"
    )
    rows = _client(app_layout).get(f"{API}/{app_layout.app_name}/experiments").json()
    by_verstr = {r["verstr"]: r for r in rows}

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
    client = _client(app_layout)

    rows = client.get(f"{API}/{app_layout.app_name}/experiments").json()
    outer = next(r for r in rows if r["verstr"] == "0.0.1")
    assert outer["status"] == "succeeded"
    assert outer["tree_status"] == "failed"

    detail = client.get(f"{API}/{app_layout.app_name}/experiments/0.0.1").json()
    assert detail["status"]["tree_status"] == "failed"
    assert sorted(detail["status"]["children"]) == ["0.0.2", "0.0.3"]


def test_last_metric_at_tracks_newest_metrics_entry(app_layout):
    _write_experiment(
        app_layout,
        "0.0.1",
        run_state=_running_state(),
        metrics=[
            ("2026-09-21T12:00:00Z", {"loss": 0.5}),
            ("2026-09-21T12:05:00Z", {"loss": 0.3}),
        ],
    )
    client = _client(app_layout)
    rows = client.get(f"{API}/{app_layout.app_name}/experiments").json()
    assert rows[0]["last_metric_at"] == "2026-09-21T12:05:00Z"

    detail = client.get(f"{API}/{app_layout.app_name}/experiments/0.0.1").json()
    assert detail["status"]["last_metric_at"] == "2026-09-21T12:05:00Z"


def test_status_is_recomputed_on_a_cache_hit(app_layout, monkeypatch):
    """A cached row must not freeze `running`: status is derived per request."""
    import version_stamp.core.experiment_status as status_mod
    import version_stamp.ui.index as index_mod

    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    idx = _index(app_layout)
    assert idx.list_experiments(app_layout.app_name)[0]["status"] == "running"

    def _boom(*a, **kw):
        raise AssertionError("cache miss: status must be derived, not re-fetched")

    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    monkeypatch.setattr(index_mod, "_fetch_experiment_rows", _boom)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or later)

    # Same files, same fingerprint, cache still warm — an hour later the run's
    # heartbeat is stale, so the served status must be stuck.
    assert idx.list_experiments(app_layout.app_name)[0]["status"] == "stuck"


def test_appending_to_a_writer_log_invalidates_the_cache(app_layout):
    _write_experiment(
        app_layout,
        "0.0.1",
        run_state=_running_state(),
        metrics=[("2026-09-21T12:00:00Z", {"loss": 0.5})],
    )
    idx = _index(app_layout)
    warm = idx.list_experiments(app_layout.app_name)
    assert warm[0]["metrics"]["loss"] == 0.5

    _append_metrics(app_layout, "0.0.1", "2026-09-21T12:09:00Z", {"loss": 0.1})
    rows = idx.list_experiments(app_layout.app_name)
    assert rows[0]["metrics"]["loss"] == 0.1
    assert rows[0]["last_metric_at"] == "2026-09-21T12:09:00Z"


def test_heartbeat_rewrite_skips_the_expensive_fetch(app_layout, monkeypatch):
    """The volatile run-state cache absorbs heartbeats.

    A rewritten ``run_state.yml`` must serve a new status without re-reading
    every experiment's metadata and logs.
    """
    import version_stamp.ui.index as index_mod

    _write_experiment(
        app_layout,
        "0.0.1",
        run_state=_running_state(),
        metrics=[("2026-09-21T12:00:00Z", {"loss": 0.5})],
    )
    idx = _index(app_layout)
    assert idx.list_experiments(app_layout.app_name)[0]["status"] == "running"

    def _boom(*a, **kw):
        raise AssertionError("a heartbeat invalidated the expensive row cache")

    monkeypatch.setattr(index_mod, "_fetch_experiment_rows", _boom)

    path = os.path.join(_exp_dir(app_layout, "0.0.1"), "run_state.yml")
    with open(path, "w") as f:
        yaml.dump(_finished_state(3), f, sort_keys=False)
    later = os.stat(path).st_mtime + 5
    os.utime(path, (later, later))

    row = idx.list_experiments(app_layout.app_name)[0]
    assert row["status"] == "failed"  # read from the fresh run state
    assert row["metrics"]["loss"] == 0.5  # served from the untouched heavy cache


def test_detail_status_only_reads_its_own_subtree(app_layout, monkeypatch):
    """A run-detail read must not scan the whole workspace for its status."""
    from version_stamp.ui.readers import experiments as exp_reader

    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    _write_experiment(
        app_layout, "0.0.2", run_state=_finished_state(0), parent="0.0.1"
    )
    _write_experiment(
        app_layout, "0.0.3", run_state=_finished_state(1), parent="0.0.1"
    )
    for verstr in ("0.0.4", "0.0.5", "0.0.6"):
        _write_experiment(app_layout, verstr, run_state=_running_state())

    run_state_reads = []
    real_run_state = exp_reader.load_run_state
    log_reads = []
    real_log = exp_reader._load_log

    def _counted_run_state(storage, app_name, verstr):
        run_state_reads.append(verstr)
        return real_run_state(storage, app_name, verstr)

    def _counted_log(storage, app_name, verstr):
        log_reads.append(verstr)
        return real_log(storage, app_name, verstr)

    monkeypatch.setattr(exp_reader, "load_run_state", _counted_run_state)
    monkeypatch.setattr(exp_reader, "_load_log", _counted_log)

    detail = (
        _client(app_layout)
        .get(f"{API}/{app_layout.app_name}/experiments/0.0.1")
        .json()
    )

    assert detail["status"]["tree_status"] == "failed"
    assert sorted(detail["status"]["children"]) == ["0.0.2", "0.0.3"]
    assert sorted(set(run_state_reads)) == ["0.0.1", "0.0.2", "0.0.3"]
    assert log_reads == ["0.0.1"]  # only the experiment being shown


@pytest.mark.parametrize("use_index", [True, False])
def test_status_filter_applies_before_pagination(app_layout, use_index):
    """``total`` counts filtered rows, so paging walks the filtered set."""
    _seed_all_statuses(app_layout)
    client = _client(app_layout, use_index=use_index)
    url = f"{API}/{app_layout.app_name}/experiments"
    params = {"status": "running,stuck", "limit": 1}

    first = client.get(url, params=params).json()
    assert first["total"] == 2
    assert [r["verstr"] for r in first["rows"]] == ["0.0.2"]

    second = client.get(url, params={**params, "offset": 1}).json()
    assert second["total"] == 2
    assert [r["verstr"] for r in second["rows"]] == ["0.0.3"]


def test_status_query_filter(app_layout):
    _seed_all_statuses(app_layout)
    client = _client(app_layout)
    url = f"{API}/{app_layout.app_name}/experiments"

    rows = client.get(url, params={"status": "running,stuck"}).json()
    assert sorted(r["verstr"] for r in rows) == ["0.0.2", "0.0.3"]

    rows = client.get(url, params={"status": "failed"}).json()
    assert [r["verstr"] for r in rows] == ["0.0.5"]

    assert client.get(url, params={"status": "bogus"}).json() == []


def test_existing_list_row_keys_are_unchanged(app_layout):
    _write_experiment(app_layout, "0.0.1", run_state=_running_state())
    rows = _client(app_layout).get(f"{API}/{app_layout.app_name}/experiments").json()

    row = rows[0]
    assert row["idx"] == 1
    for key in (
        "verstr",
        "code_verstr",
        "timestamp",
        "note",
        "branch",
        "base_version",
        "user_meta",
        "metrics",
    ):
        assert key in row, key


def test_indexed_and_direct_rows_agree(app_layout):
    from version_stamp.ui.readers import experiments as exp_reader

    _seed_all_statuses(app_layout)
    direct = exp_reader.list_experiments(app_layout.repo_path, app_layout.app_name)
    indexed = _index(app_layout).list_experiments(app_layout.app_name)
    assert [r["status"] for r in indexed] == [r["status"] for r in direct]
    assert [r["verstr"] for r in indexed] == [r["verstr"] for r in direct]
