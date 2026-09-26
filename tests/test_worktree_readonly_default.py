from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from helpers import _init_app, _run_vmn_init, _stamp_app
from version_stamp.cli import commands, entry
from version_stamp.cli.args import parse_user_commands
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import init_stamp_logger
from version_stamp.stamping.publisher import _push_published_refs


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


class Args(SimpleNamespace):
    def __contains__(self, name):
        return hasattr(self, name)


def test_no_stamp_flag_is_gone():
    with pytest.raises(SystemExit):
        parse_user_commands(["worktrees", "create", "app", "--no-stamp"])


def test_publish_always_pushes_branch_and_checks_outgoing():
    calls = []
    backend = SimpleNamespace(
        push=lambda tags: calls.append(("branch", tags)),
        check_for_outgoing_changes=lambda: None,
    )

    _push_published_refs(backend, ["app_1.2.3"])

    assert calls == [("branch", ["app_1.2.3"])]


def test_stamp_updates_always_merge_remote_branch():
    calls = []
    vcs = SimpleNamespace(
        backend=SimpleNamespace(
            perform_cached_fetch=lambda force=False: calls.append(("fetch", force))
        ),
        retrieve_remote_changes=lambda: calls.append(("pull", None)),
    )

    commands._retrieve_stamp_updates(vcs)

    assert calls == [("fetch", True), ("pull", None)]


def test_stamp_without_remote_is_refused_even_in_island(tmp_path, monkeypatch):
    backend = SimpleNamespace(selected_remote=None)
    ctx = SimpleNamespace(
        args=Args(command="stamp", pull=False),
        vcs=SimpleNamespace(backend=backend, name=None),
    )
    monkeypatch.setattr(entry, "VMNContainer", lambda args, root: ctx)

    assert entry._vmn_run(ctx.args, str(tmp_path))[0] == 1


def test_stamp_on_island_branch_is_refused_but_real_branch_stamps(
    app_layout, tmp_path, capfd
):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    remote = app_layout.test_app_remote
    base_path = tmp_path / "islands"

    assert (
        vmn_run(
            [
                "worktrees",
                "create",
                app_layout.app_name,
                "--island-name",
                "ro-test",
                "--base-path",
                str(base_path),
            ]
        )[0]
        == 0
    )
    manifest = (base_path / "ro-test" / "island.json").read_text()
    assert '"readonly"' not in manifest
    tags_before = subprocess.check_output(
        ["git", "--git-dir", remote, "tag"], text=True
    )

    island_repo = base_path / "ro-test" / Path(app_layout.repo_path).name
    app_layout.set_working_dir(str(island_repo))
    capfd.readouterr()
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    assert "island branch" in capfd.readouterr().err.lower()
    assert (
        subprocess.check_output(["git", "--git-dir", remote, "tag"], text=True)
        == tags_before
    )

    for cmd in (
        ["checkout", "-q", "-b", "feature/in-island"],
        ["commit", "-q", "--allow-empty", "-m", "island work"],
        ["push", "-q", "-u", "origin", "feature/in-island"],
    ):
        subprocess.run(["git", "-C", str(island_repo), *cmd], check=True)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    branches = subprocess.check_output(
        ["git", "--git-dir", remote, "branch", "--format=%(refname:short)"], text=True
    ).split()
    assert "feature/in-island" in branches

    app_layout.set_working_dir(app_layout.repo_path)
    assert (
        vmn_run(["worktrees", "remove", "ro-test", "--base-path", str(base_path)])[0]
        == 0
    )


def test_create_writes_no_marker_files(app_layout, tmp_path):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    base_path = tmp_path / "islands"

    assert (
        vmn_run(
            [
                "worktrees",
                "create",
                app_layout.app_name,
                "--island-name",
                "no-markers",
                "--base-path",
                str(base_path),
            ]
        )[0]
        == 0
    )

    island_vmn = base_path / "no-markers" / Path(app_layout.repo_path).name / ".vmn"
    assert not (island_vmn / ".worktree-readonly").exists()
    assert not (island_vmn / ".worktree-island").exists()
