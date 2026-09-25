import os

import pytest

fastapi = pytest.importorskip("fastapi")

from helpers import _init_app, _run_vmn_init, _stamp_app


def test_ui_args_parse():
    from version_stamp.cli.args import parse_user_commands

    args = parse_user_commands(
        [
            "ui",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--token",
            "t0k",
            "--data-dir",
            "/tmp/x",
            "--repo",
            "/r1",
            "--repo",
            "/r2",
            "--s3-bucket",
            "bkt",
            "--s3-prefix",
            "team/ml",
            "--endpoint-url",
            "http://minio:9000",
            "--read-only",
            "--no-browser",
            "--no-index",
        ]
    )
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
    args = parse_user_commands(
        [
            "ui",
            "--data-dir",
            data_dir,
            "--repo",
            app_layout.repo_path,
            "--s3-bucket",
            "team-bucket",
            "--s3-prefix",
            "ml",
        ]
    )
    manager = build_manager(args)

    by_name = {w.name: w for w in manager.list()}
    assert any(
        w.kind == "git" and w.path == app_layout.repo_path for w in by_name.values()
    )
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


# ---------------------------------------------------------------------------
# Non-loopback bind without a token: the Host-header allowlist is not
# authentication, so a plain LAN client can forge an allowed Host and get
# full read-write access. `handle_ui` must refuse this combination instead
# of just warning and serving read-write anyway.
# ---------------------------------------------------------------------------


def _run_handle_ui(tmp_path, monkeypatch, extra):
    from version_stamp.cli.args import parse_user_commands
    from version_stamp.core.logging import init_stamp_logger, reset_logger
    from version_stamp.ui.cli import handle_ui

    reset_logger()
    init_stamp_logger()
    monkeypatch.chdir(tmp_path)

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: calls.append((a, k)))

    data_dir = str(tmp_path / "ui_data")
    args = parse_user_commands(["ui", "--data-dir", data_dir, "--no-browser"] + extra)
    rc = handle_ui(args)
    return rc, calls


def test_ui_refuses_non_loopback_without_token_or_read_only(tmp_path, monkeypatch, capfd):
    rc, calls = _run_handle_ui(tmp_path, monkeypatch, ["--host", "0.0.0.0"])

    assert rc == 1
    assert calls == []
    captured = capfd.readouterr()
    assert "[ERROR]" in captured.err
    assert "--token" in captured.err
    assert "--read-only" in captured.err


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(["--host", "0.0.0.0", "--read-only"], id="non-loopback-read-only"),
        pytest.param([], id="loopback-no-token"),
        pytest.param(["--host", "0.0.0.0", "--token", "t0k"], id="non-loopback-with-token"),
    ],
)
def test_ui_starts_read_write_when_safely_configured(tmp_path, monkeypatch, capfd, extra):
    """Regression: read-only-without-a-token, loopback-without-a-token and
    non-loopback-with-a-token must all keep starting the server, unchanged."""
    rc, calls = _run_handle_ui(tmp_path, monkeypatch, extra)

    assert rc == 0
    assert len(calls) == 1
    captured = capfd.readouterr()
    assert "[ERROR]" not in captured.err
