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


def test_ui_exp_create_build_command():
    """exp_create translates note + metrics into a `vmn experiment create` argv."""
    from version_stamp.ui.jobs import build_command

    cmd, err = build_command(
        "exp_create", "my_app", {"note": "swin-t", "metrics": {"loss": 0.1, "acc": 0.9}}
    )
    assert err is None
    assert cmd == [
        "vmn", "experiment", "create", "my_app",
        "--note", "swin-t", "--metrics", "loss=0.1", "acc=0.9",
    ]

    cmd, err = build_command("exp_create", "my_app", {})
    assert err is None
    assert cmd == ["vmn", "experiment", "create", "my_app"]

    cmd, err = build_command("exp_create", "my_app", {"metrics": {"bad key": 1}})
    assert cmd is None and err

    cmd, err = build_command("exp_create", "my_app", {"metrics": {"k=v": 1}})
    assert cmd is None and err


def test_ui_exp_create_action(app_layout, capfd):
    """POST actions/exp_create captures the working state as an experiment."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "e.txt", "committed")
    with open(os.path.join(app_layout.repo_path, "e.txt"), "w") as f:
        f.write("dirty state")

    client = _client(app_layout)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/exp_create",
        json={"note": "from the ui", "metrics": {"loss": 0.42}},
    )
    assert r.status_code == 202
    job = _wait_job(client, f"/api/v1/jobs/{r.json()['id']}")
    assert job["status"] == "succeeded", job.get("log")

    rows = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/experiments"
    ).json()
    assert len(rows) == 1
    assert rows[0]["note"] == "from the ui"
    assert rows[0]["metrics"]["loss"] == 0.42


def test_ui_goto_build_command_version_optional():
    """`goto` accepts an empty version: goes to the tip of the branch,
    matching `vmn goto <app>` with no `-v`."""
    from version_stamp.ui.jobs import build_command

    cmd, err = build_command("goto", "my_app", {})
    assert err is None
    assert cmd == ["vmn", "goto", "my_app"]

    cmd, err = build_command("goto", "my_app", {"verstr": ""})
    assert err is None
    assert cmd == ["vmn", "goto", "my_app"]

    cmd, err = build_command("goto", "my_app", {"verstr": "1.2.0"})
    assert err is None
    assert cmd == ["vmn", "goto", "-v", "1.2.0", "my_app"]


def test_ui_goto_action_without_version(app_layout, capfd):
    """POST actions/goto with no verstr goes to the tip of the branch."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "g.txt", "x")
    _stamp_app(app_layout.app_name, "minor")

    client = _client(app_layout)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/goto",
        json={},
    )
    assert r.status_code == 202
    job = _wait_job(client, f"/api/v1/jobs/{r.json()['id']}")
    assert job["status"] == "succeeded", job.get("log")
    assert "tip of the branch" in job["log"]


def test_ui_snapshot_create_build_command():
    from version_stamp.ui.jobs import build_command

    cmd, err = build_command("snapshot_create", "my_app", {"note": "wip refactor"})
    assert err is None
    assert cmd == ["vmn", "snapshot", "create", "my_app", "--note", "wip refactor"]

    cmd, err = build_command("snapshot_create", "my_app", {})
    assert err is None
    assert cmd == ["vmn", "snapshot", "create", "my_app"]


def test_ui_snapshot_create_action(app_layout, capfd):
    """POST actions/snapshot_create captures the dirty working tree."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "s.txt", "committed")
    with open(os.path.join(app_layout.repo_path, "s.txt"), "w") as f:
        f.write("dirty state")

    client = _client(app_layout)
    r = client.post(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/actions/snapshot_create",
        json={"note": "from the ui"},
    )
    assert r.status_code == 202
    job = _wait_job(client, f"/api/v1/jobs/{r.json()['id']}")
    assert job["status"] == "succeeded", job.get("log")

    rows = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/snapshots"
    ).json()
    assert len(rows) == 1
    assert rows[0]["note"] == "from the ui"


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
