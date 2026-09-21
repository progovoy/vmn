"""End-to-end: status written by `vmn exp run` is what the web API serves.

The CLI-side and ui-side tests each mock the other's half of ``run_state.yml``
(one writes it, one hand-crafts it). These tests drive the real CLI and then
read through the real HTTP API, so a drift in that file's shape — a renamed
key, a different timestamp format — fails here instead of silently reporting
every run as ``created``.
"""
import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from helpers import _PROJECT_ROOT, _PY, _bootstrap, _exec_script, _exp

API = "/api/v1/workspaces/main/apps"


def _client(app_layout, use_index=True):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceError, WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    try:
        manager.attach_path("main", app_layout.repo_path)
    except WorkspaceError:
        pass  # a previous client in this test already attached it
    return TestClient(create_app(manager, use_index=use_index))


def _rows(app_layout, use_index=True, **params):
    client = _client(app_layout, use_index=use_index)
    resp = client.get(f"{API}/{app_layout.app_name}/experiments", params=params)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["rows"] if isinstance(body, dict) else body


def _detail(app_layout, verstr):
    client = _client(app_layout)
    resp = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr}")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize(
    "exit_code,expected",
    [(0, "succeeded"), (3, "failed")],
)
def test_real_run_status_reaches_the_api(app_layout, capfd, exit_code, expected):
    _bootstrap(app_layout)
    script = _exec_script(
        app_layout,
        "job.py",
        "import os, sys\n"
        "open(os.environ['VMN_METRICS_FILE'], 'a').write('loss=0.25\\n')\n"
        f"sys.exit({exit_code})\n",
    )
    capfd.readouterr()
    err = _exp(app_layout.app_name, action="run", run_cmd=[_PY, script])
    assert err == exit_code

    rows = _rows(app_layout)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == expected
    assert row["exit_code"] == exit_code
    assert row["duration_sec"] is not None
    assert row["started_at"] and row["finished_at"]
    assert row["command"][-1].endswith("job.py")
    assert row["pid"] and row["host"]
    assert row["kind"] == "single"
    assert row["metrics"]["loss"] == 0.25
    assert row["last_metric_at"] is not None

    detail = _detail(app_layout, row["verstr"])
    assert detail["status"]["status"] == expected
    assert detail["status"]["exit_code"] == exit_code
    # pre-existing keys must survive
    for key in ("metadata", "log", "metrics", "series", "artifacts", "patches"):
        assert key in detail


def test_created_experiment_reports_created(app_layout, capfd):
    _bootstrap(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, note="no run here") == 0

    row = _rows(app_layout)[0]
    assert row["status"] == "created"
    assert row["exit_code"] is None
    assert row["command"] is None
    assert row["duration_sec"] is None


def test_nested_sweep_is_outer_and_inner_through_the_api(app_layout, capfd):
    """A sweep script calling `vmn exp run` per trial: one outer, two inner."""
    _bootstrap(app_layout)
    trial = _exec_script(
        app_layout,
        "trial.py",
        "import os\n"
        "open(os.environ['VMN_METRICS_FILE'], 'a').write('loss=0.5\\n')\n",
    )
    env_path = os.environ.get("PYTHONPATH", "")
    sweep = _exec_script(
        app_layout,
        "sweep.sh",
        "#!/bin/sh\nset -e\n"
        f'export PYTHONPATH="{_PROJECT_ROOT}:{env_path}"\n'
        f"for i in 1 2; do\n"
        f'  "{_PY}" -m version_stamp.cli.entry exp run '
        f'{app_layout.app_name} -- "{_PY}" "{trial}"\n'
        "done\n",
    )
    capfd.readouterr()
    err = _exp(app_layout.app_name, action="run", run_cmd=[sweep])
    assert err == 0

    rows = _rows(app_layout)
    outer = [r for r in rows if r["kind"] == "outer"]
    inner = [r for r in rows if r["kind"] == "inner"]
    assert len(outer) == 1, [(r["verstr"], r["kind"]) for r in rows]
    assert len(inner) == 2
    assert sorted(outer[0]["children"]) == sorted(r["verstr"] for r in inner)
    for row in inner:
        assert row["parent"] == outer[0]["verstr"]
        assert row["depth"] == 1
        assert row["status"] == "succeeded"
    assert outer[0]["depth"] == 0
    assert outer[0]["tree_status"] == "succeeded"

    detail = _detail(app_layout, outer[0]["verstr"])
    assert detail["status"]["kind"] == "outer"
    assert len(detail["status"]["children"]) == 2


def test_failed_inner_makes_the_sweep_read_as_failed(app_layout, capfd):
    _bootstrap(app_layout)
    trial = _exec_script(app_layout, "boom.py", "import sys\nsys.exit(1)\n")
    env_path = os.environ.get("PYTHONPATH", "")
    sweep = _exec_script(
        app_layout,
        "sweep.sh",
        "#!/bin/sh\n"
        f'export PYTHONPATH="{_PROJECT_ROOT}:{env_path}"\n'
        f'"{_PY}" -m version_stamp.cli.entry exp run '
        f'{app_layout.app_name} -- "{_PY}" "{trial}" || true\n',
    )
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="run", run_cmd=[sweep]) == 0

    rows = _rows(app_layout)
    outer = next(r for r in rows if r["kind"] == "outer")
    assert outer["status"] == "succeeded", "the sweep script itself exited 0"
    assert outer["tree_status"] == "failed", "but a trial failed"


def test_status_filter_over_real_runs(app_layout, capfd):
    _bootstrap(app_layout)
    ok = _exec_script(app_layout, "ok.py", "pass\n")
    bad = _exec_script(app_layout, "bad.py", "import sys\nsys.exit(2)\n")
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="run", run_cmd=[_PY, ok]) == 0
    app_layout.write_file_commit_and_push("test_repo_0", "churn.txt", "x")
    assert _exp(app_layout.app_name, action="run", run_cmd=[_PY, bad]) == 2

    failed = _rows(app_layout, status="failed")
    assert [r["status"] for r in failed] == ["failed"]
    assert len(_rows(app_layout, status="succeeded,failed")) == 2
    assert _rows(app_layout, status="running") == []
