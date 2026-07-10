import os

import pytest
import yaml

from helpers import _init_app, _run_vmn_init, _show, _stamp_app


def test_vmn_init(app_layout, capfd):
    res = _run_vmn_init()
    assert res == 0
    captured = capfd.readouterr()

    assert (
        f"[INFO] Initialized vmn tracking on {app_layout.repo_path}\n" == captured.out
    )
    assert "" == captured.err

    res = _run_vmn_init()
    assert res == 1

    captured = capfd.readouterr()
    assert captured.err.startswith("[ERROR] vmn repo tracking is already initialized")
    assert "" == captured.out


def test_vmn_init_gitignores_snapshot_dirs(app_layout):
    """vmn init should gitignore snapshot and experiment directories."""
    res = _run_vmn_init()
    assert res == 0

    gitignore_path = os.path.join(app_layout.repo_path, ".vmn", ".gitignore")
    assert os.path.exists(gitignore_path)
    with open(gitignore_path) as f:
        content = f.read()
    assert "snapshots" in content.lower(), (
        f".vmn/.gitignore missing snapshots pattern: {content}"
    )
    assert "experiments" in content.lower(), (
        f".vmn/.gitignore missing experiments pattern: {content}"
    )


def test_double_stamp_no_commit(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    for i in range(2):
        err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_app2_and_app1_not_advance(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    new_name = f"{app_layout.app_name}_2"
    _init_app(new_name, "1.0.0")

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.1"

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_stamp_multiple_apps(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    new_name = f"{app_layout.app_name}_2"
    _init_app(new_name, "1.0.0")

    _stamp_app(new_name, "hotfix")

    repo_name = app_layout.repo_path.split(os.path.sep)[-1]
    app_layout.write_file_commit_and_push(
        f"{repo_name}", os.path.join("a", "b", "c", "f1.file"), "msg1"
    )
    os.environ[
        "VMN_WORKING_DIR"
    ] = f"{os.path.join(app_layout.repo_path, 'a', 'b', 'c')}"

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.2"

    for i in range(2):
        err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "0.0.2"

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.2"

    _init_app("myapp")


@pytest.mark.parametrize("hook_name", ["pre-push", "post-commit", "pre-commit"])
def test_git_hooks(app_layout, capfd, hook_name):
    res = _run_vmn_init()
    assert res == 0
    res = _run_vmn_init()
    assert res == 1
    _, _, params = _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "connnntenctt")

    # More post-checkout, post-commit, post-merge, post-rewrite, pre-commit, pre-push
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        f".git/hooks/{hook_name}",
        "#/bin/bash\nexit 1",
        add_exec=True,
        commit=False,
    )

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["out"] == "0.0.1"
    assert "version_not_matched" in tmp["dirty"]

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 1

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["out"] == "0.0.1"
    assert "version_not_matched" in tmp["dirty"]

    app_layout.remove_file(
        os.path.join(params["root_path"], f".git/hooks/{hook_name}"), from_git=False
    )

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.2\n" == captured.out


def test_stamp_on_branch_merge_squash(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("new_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    app_layout._app_backend.selected_remote.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout._app_backend.selected_remote.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout.write_file_commit_and_push("test_repo_0", "f3.file", "msg3")
    app_layout._app_backend.selected_remote.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout._app_backend.be.checkout(main_branch)
    app_layout.merge(from_rev="new_branch", to_rev=main_branch, squash=True)
    app_layout._app_backend.selected_remote.pull(rebase=True)

    app_layout._app_backend.be.push()

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]

    assert data["_version"] == "1.3.3"


def test_basic_root_stamp(app_layout):
    _run_vmn_init()

    app_name = "root_app/app1"
    _init_app(app_name)

    err, ver_info, params = _stamp_app(app_name, "patch")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"

    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 1

    app_name = "root_app/app2"
    _init_app(app_name)
    err, ver_info, params = _stamp_app(app_name, "minor")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 3

    app_name = "root_app/app3"
    _init_app(app_name)
    err, ver_info, params = _stamp_app(app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 5

    app_name = "root_app/app1"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 1

    app_name = "root_app/app2"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 3

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "blabla")

    app_name = "root_app/app1"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 6
    assert "root_app/app1" in data["services"]
    assert "root_app/app2" in data["services"]

    app_name = "root_app/app2"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 7

    assert data["services"]["root_app/app1"] == "1.0.0"
    assert data["services"]["root_app/app2"] == "1.0.0"
    assert data["services"]["root_app/app3"] == "0.0.1"


def test_starting_version(app_layout, capfd):
    _run_vmn_init()
    capfd.readouterr()
    _init_app(app_layout.app_name, "1.2.3")
    captured = capfd.readouterr()

    path = f"{os.path.join(app_layout.repo_path, '.vmn', app_layout.app_name)}"
    assert f"[INFO] Initialized app tracking on {path}\n" == captured.out

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"


def test_stamp_no_ff_rebase(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    main_branch = app_layout._app_backend.be.get_active_branch()
    other_branch = "topic"

    app_layout.checkout(other_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg1")
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")

    app_layout.rebase(main_branch, other_branch, no_ff=True)

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.2" == res["out"]


@pytest.mark.parametrize("branch_name", ["new_branch", "new_branch/a"])
def test_no_upstream_branch_stamp(app_layout, capfd, branch_name):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    app_layout.checkout(branch_name, create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    main_branch = app_layout._app_backend.be.get_active_branch()
    assert branch_name == main_branch

    app_layout._app_backend.be._be.git.branch("--unset-upstream", main_branch)

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.1"


def test_stamp_auto_init(app_layout):
    """vmn stamp on a completely fresh repo should auto-init repo + app and stamp 0.0.1."""
    # Do NOT call _run_vmn_init() or _init_app() — that's the whole point.
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info is not None
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"
