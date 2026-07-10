import os
import subprocess
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from helpers import (
    _experiment,
    _init_app,
    _run_vmn_init,
    _stamp_app,
    extract_dev_verstr,
)


def _client(app_layout, read_only=False, extra=None):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    for name, path in (extra or {}).items():
        manager.attach_path(name, path)
    return TestClient(create_app(manager, read_only=read_only))


def _wait_job(client, job_url, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(job_url).json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_ui_stamp_action(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1
    app_layout.write_file_commit_and_push("test_repo_0", "s.txt", "x")

    client = _client(app_layout)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/stamp",
        json={"release_mode": "minor"},
    )
    assert r.status_code == 202
    job = _wait_job(client, f"/api/v1/jobs/{r.json()['id']}")
    assert job["status"] == "succeeded", job.get("log")
    assert job["exit_code"] == 0

    versions = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/versions"
    ).json()
    assert versions[-1]["verstr"] == "0.1.0"


def test_ui_stamp_dry_run(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "d.txt", "x")

    client = _client(app_layout)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/stamp",
        json={"release_mode": "patch", "dry_run": True},
    )
    job = _wait_job(client, f"/api/v1/jobs/{r.json()['id']}")
    assert job["status"] == "succeeded"

    # Dry run must not create a new version.
    versions = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/versions"
    ).json()
    assert versions[-1]["verstr"] == "0.0.1"


def test_ui_restore_action_with_safety_net(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout.write_file_commit_and_push("test_repo_0", "r.txt", "committed")
    p = os.path.join(app_layout.repo_path, "r.txt")
    with open(p, "w") as f:
        f.write("state A")
    capfd.readouterr()
    _experiment(app_layout.app_name, note="A")
    v_a = extract_dev_verstr(capfd.readouterr().out)

    # Different, unsaved state.
    with open(p, "w") as f:
        f.write("state B unsaved")

    client = _client(app_layout)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/restore",
        json={"verstr": v_a},
    )
    assert r.status_code == 202
    job = _wait_job(client, f"/api/v1/jobs/{r.json()['id']}")
    assert job["status"] == "succeeded", job.get("log")

    with open(p) as f:
        assert f.read() == "state A"
    # Safety net preserved the unsaved state B as a snapshot (recoverable).
    snaps = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/snapshots"
    ).json()
    assert len(snaps) == 1
    assert "auto-saved before restore" in (snaps[0]["note"] or "")


def test_ui_read_only_blocks_mutations(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    client = _client(app_layout, read_only=True)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/stamp",
        json={"release_mode": "patch"},
    )
    assert r.status_code == 403


def test_ui_action_cli_preview(app_layout, capfd):
    """Every action exposes its CLI equivalent for reproducibility."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    client = _client(app_layout)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/stamp",
        json={"release_mode": "minor", "dry_run": True},
    )
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["command"][:2] == ["vmn", "stamp"]
    assert "-r" in job["command"] and "minor" in job["command"]


def test_ui_workspace_isolation_on_stamp(app_layout, capfd):
    """A stamp in workspace A does not touch workspace B (a second clone)."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1 shared via tags

    second = os.path.join(app_layout.base_dir, "second_clone")
    subprocess.run(
        ["git", "clone", app_layout.test_app_remote, second],
        capture_output=True, check=True,
    )
    app_layout.write_file_commit_and_push("test_repo_0", "iso.txt", "x")

    client = _client(app_layout, extra={"second": second})
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/stamp",
        json={"release_mode": "minor"},
    )
    _wait_job(client, f"/api/v1/jobs/{r.json()['id']}")

    # main advanced; second (not fetched) still sees only the shared 0.0.1.
    main_v = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/versions"
    ).json()
    second_v = client.get(
        f"/api/v1/workspaces/second/apps/{app_layout.app_name}/versions"
    ).json()
    assert main_v[-1]["verstr"] == "0.1.0"
    assert second_v[-1]["verstr"] == "0.0.1"
    assert not os.path.exists(os.path.join(second, "iso.txt"))
