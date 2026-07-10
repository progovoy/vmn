import os

import pytest

fastapi = pytest.importorskip("fastapi")

from helpers import _init_app, _run_vmn_init, _stamp_app


def test_ui_args_parse():
    from version_stamp.cli.args import parse_user_commands

    args = parse_user_commands([
        "ui", "--host", "0.0.0.0", "--port", "9000",
        "--token", "t0k", "--data-dir", "/tmp/x",
        "--repo", "/r1", "--repo", "/r2",
        "--s3-bucket", "bkt", "--s3-prefix", "team/ml",
        "--endpoint-url", "http://minio:9000",
        "--read-only", "--no-browser", "--no-index",
    ])
    assert args.command == "ui"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.token == "t0k"
    assert args.data_dir == "/tmp/x"
    assert args.repo == ["/r1", "/r2"]
    assert args.s3_bucket == "bkt"
    assert args.read_only is True
    assert args.no_browser is True
    assert args.no_index is True


def test_ui_defaults_parse():
    from version_stamp.cli.args import parse_user_commands

    args = parse_user_commands(["ui"])
    assert args.host == "127.0.0.1"
    assert args.port == 8265
    assert args.token is None
    assert args.read_only is False


def test_ui_build_manager_from_args(app_layout, capfd):
    """--repo paths and S3 sources become workspaces; cwd repo is implicit."""
    from version_stamp.cli.args import parse_user_commands
    from version_stamp.ui.cli import build_manager

    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    data_dir = os.path.join(app_layout.base_dir, "ui_data")
    args = parse_user_commands([
        "ui", "--data-dir", data_dir,
        "--repo", app_layout.repo_path,
        "--s3-bucket", "team-bucket", "--s3-prefix", "ml",
    ])
    manager = build_manager(args)

    by_name = {w.name: w for w in manager.list()}
    assert any(w.kind == "git" and w.path == app_layout.repo_path
               for w in by_name.values())
    s3 = [w for w in by_name.values() if w.kind == "s3"]
    assert len(s3) == 1
    assert s3[0].bucket == "team-bucket"
    assert s3[0].prefix == "ml"


def test_ui_build_manager_cwd_repo(app_layout, capfd, monkeypatch):
    """Run inside a repo with no sources: the cwd repo is auto-attached."""
    from version_stamp.cli.args import parse_user_commands
    from version_stamp.ui.cli import build_manager

    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    data_dir = os.path.join(app_layout.base_dir, "ui_data2")
    monkeypatch.chdir(app_layout.repo_path)
    args = parse_user_commands(["ui", "--data-dir", data_dir])
    manager = build_manager(args)

    workspaces = manager.list()
    assert len(workspaces) == 1
    assert os.path.realpath(workspaces[0].path) == os.path.realpath(
        app_layout.repo_path
    )


def test_ui_build_manager_idempotent(app_layout, capfd):
    """Re-running with the same sources doesn't duplicate workspaces."""
    from version_stamp.cli.args import parse_user_commands
    from version_stamp.ui.cli import build_manager

    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    data_dir = os.path.join(app_layout.base_dir, "ui_data3")
    args = parse_user_commands(
        ["ui", "--data-dir", data_dir, "--repo", app_layout.repo_path]
    )
    m1 = build_manager(args)
    n1 = len(m1.list())
    m2 = build_manager(args)
    assert len(m2.list()) == n1
