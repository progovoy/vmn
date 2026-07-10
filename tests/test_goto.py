import os
import shutil
import subprocess

import git
import yaml

from helpers import (
    _configure_2_deps,
    _goto,
    _init_app,
    _release_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


def test_basic_goto(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.1"

    c1 = app_layout._app_backend.be.changeset()
    err = _goto(app_layout.app_name, version="0.0.2")
    assert err == 1

    err = _goto(app_layout.app_name, version="1.3.0")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    captured = capfd.readouterr()
    assert (
        "[INFO] Found existing version 1.3.0 and nothing has changed. Will not stamp\n"
        == captured.out
    )

    c2 = app_layout._app_backend.be.changeset()
    assert c1 != c2
    err = _goto(app_layout.app_name, version="1.3.1")
    assert err == 0
    c3 = app_layout._app_backend.be.changeset()
    assert c1 == c3

    err = _goto(app_layout.app_name)
    assert err == 0

    c4 = app_layout._app_backend.be.changeset()
    assert c1 == c4

    root_app_name = "some_root_app/service1"
    _init_app(root_app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc1 = app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc2 = app_layout._app_backend.be.changeset()

    assert rc1 != rc2

    err = _goto(root_app_name, version="1.3.0")
    assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    err = _goto(root_app_name)
    assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.5.0"

    rc3 = app_layout._app_backend.be.changeset()

    root_name = root_app_name.split("/")[0]

    err = _goto(root_name, version="1", root=True)
    assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    err = _goto(root_name, root=True)
    assert err == 0

    assert rc3 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    deps = ver_info["stamping"]["app"]["changesets"]

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash']}",
    )
    assert err == 0

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash'][:-10]}",
    )
    assert err == 0

    capfd.readouterr()

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash'][:-10]}X",
    )
    assert err == 1

    captured = capfd.readouterr()
    assert "[ERROR] Wrong unique id\n" == captured.err


def test_goto_print(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")

    app_layout.write_file_commit_and_push("test_repo_0", "my.js", "some text")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="major")

    capfd.readouterr()

    err = _goto(app_layout.app_name, version="1.3.0")
    assert err == 0

    sout, serr = capfd.readouterr()
    assert f"[INFO] You are at version 1.3.0 of {app_layout.app_name}\n" == sout

    err = _goto(app_layout.app_name)
    assert err == 0

    sout, serr = capfd.readouterr()
    assert (
        f"[INFO] You are at the tip of the branch of version 2.0.0 for {app_layout.app_name}\n"
        == sout
    )


def test_goto_deleted_repos(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    dir_path = app_layout._repos["repo2"]["path"]
    # deleting repo_b
    shutil.rmtree(dir_path)

    err = _goto(app_layout.app_name, version="0.0.2")
    assert err == 0


def test_rc_goto(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    try:
        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="minor", prerelease="rc_aaa"
        )
        assert err == 0
    except AssertionError:
        pass

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rcaaa"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rcaaa.1"

    err = _goto(app_layout.app_name, version="1.3.0-rcaaa.1")
    assert err == 0


def test_dirty_no_ff_rebase(app_layout, capfd):
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

    app_layout.rebase(main_branch, other_branch, no_ff=True)

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.2" == res["out"]
    assert len(res["dirty"]) == 2
    assert "version_not_matched" in res["dirty"]
    assert "outgoing" in res["dirty"]


def test_goto_clones_and_checks_out_new_dep_from_branch_specific_conf(app_layout):
    from version_stamp.core.utils import branch_to_conf_prefix

    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Set up the dependency repo. create_repo() also leaves a local clone on
    # disk as a side effect of test setup - remove it below so the repo is,
    # from vmn's point of view, a dependency it has never cloned before.
    dep_be = app_layout.create_repo(repo_name="dep_repo", repo_type="git")
    dep_path = app_layout._repos["dep_repo"]["path"]
    dep_remote = app_layout._repos["dep_repo"]["remote"]

    target_branch = "general/integration/ussr_remove_async"
    app_layout.checkout(target_branch, repo_name="dep_repo", create_new=True)
    app_layout.write_file_commit_and_push("dep_repo", "f1.file", "on-branch-content")
    expected_sha = app_layout._repos["dep_repo"]["changesets"]["hash"]

    dep_be.__del__()
    shutil.rmtree(dep_path)

    # The app moves to its own branch, with a branch-specific conf.yml that
    # is the only place the dependency on target_branch is configured.
    app_branch = "topic/goto_new_dep"
    app_layout.checkout(app_branch, create_new=True)
    subprocess.call(
        ["git", "push", "-u", "origin", app_branch], cwd=app_layout.repo_path
    )

    branch_conf_path = os.path.join(
        os.path.dirname(params["app_conf_path"]),
        f"{branch_to_conf_prefix(app_branch)}_conf.yml",
    )
    app_layout.write_conf(
        branch_conf_path,
        deps={
            "../": {
                "dep_repo": {
                    "vcs_type": "git",
                    "remote": dep_remote,
                    "branch": target_branch,
                }
            }
        },
    )

    err = _goto(app_layout.app_name)
    assert err == 0

    assert os.path.isdir(dep_path)

    dep_repo_after = git.Repo(dep_path)
    assert dep_repo_after.active_branch.name == target_branch
    assert dep_repo_after.head.commit.hexsha == expected_sha
    dep_repo_after.close()


def test_goto_reads_branch_conf_from_legacy_nested_path(app_layout, capfd):
    """A branch-specific conf placed at a path mirroring the branch name with
    '/' kept as directories (e.g.
    '.vmn/<app>/general/integration/ussr_remove_async_conf.yml') is a
    supported legacy layout: vmn reads it, so a dependency declared only
    there is cloned and checked out."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    dep_be = app_layout.create_repo(repo_name="dep_repo", repo_type="git")
    dep_path = app_layout._repos["dep_repo"]["path"]
    dep_remote = app_layout._repos["dep_repo"]["remote"]

    target_branch = "general/integration/ussr_remove_async"
    app_layout.checkout(target_branch, repo_name="dep_repo", create_new=True)
    app_layout.write_file_commit_and_push("dep_repo", "f1.file", "on-branch-content")
    expected_sha = app_layout._repos["dep_repo"]["changesets"]["hash"]

    dep_be.__del__()
    shutil.rmtree(dep_path)

    app_branch = "general/integration/ussr_remove_async"
    app_layout.checkout(app_branch, create_new=True)
    subprocess.call(
        ["git", "push", "-u", "origin", app_branch], cwd=app_layout.repo_path
    )

    # Legacy layout: nested directories mirroring the branch name, instead
    # of the flattened "general-integration-ussr_remove_async_conf.yml".
    app_dir = os.path.dirname(params["app_conf_path"])
    legacy_branch_conf_path = os.path.join(app_dir, f"{app_branch}_conf.yml")
    os.makedirs(os.path.dirname(legacy_branch_conf_path), exist_ok=True)
    app_layout.write_conf(
        legacy_branch_conf_path,
        deps={
            "../": {
                "dep_repo": {
                    "vcs_type": "git",
                    "remote": dep_remote,
                    "branch": target_branch,
                }
            }
        },
    )

    capfd.readouterr()
    err = _goto(app_layout.app_name)
    assert err == 0

    assert os.path.isdir(dep_path)

    dep_repo_after = git.Repo(dep_path)
    assert dep_repo_after.active_branch.name == target_branch
    assert dep_repo_after.head.commit.hexsha == expected_sha
    dep_repo_after.close()

    captured = capfd.readouterr()
    assert "nested in a subdirectory" not in captured.err


def test_goto_clones_dep_from_canonical_branch_conf(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    dep_be = app_layout.create_repo(repo_name="dep_repo", repo_type="git")
    dep_path = app_layout._repos["dep_repo"]["path"]
    dep_remote = app_layout._repos["dep_repo"]["remote"]

    target_branch = "general/integration/ussr_remove_async"
    app_layout.checkout(target_branch, repo_name="dep_repo", create_new=True)
    app_layout.write_file_commit_and_push("dep_repo", "f1.file", "on-branch-content")
    expected_sha = app_layout._repos["dep_repo"]["changesets"]["hash"]

    dep_be.__del__()
    shutil.rmtree(dep_path)

    app_branch = "topic/goto_new_dep"
    app_layout.checkout(app_branch, create_new=True)
    subprocess.call(
        ["git", "push", "-u", "origin", app_branch], cwd=app_layout.repo_path
    )

    app_dir = os.path.dirname(params["app_conf_path"])
    canonical_conf_path = os.path.join(
        app_dir, "branch_conf", *app_branch.split("/"), "conf.yml"
    )
    os.makedirs(os.path.dirname(canonical_conf_path), exist_ok=True)
    app_layout.write_conf(
        canonical_conf_path,
        deps={
            "../": {
                "dep_repo": {
                    "vcs_type": "git",
                    "remote": dep_remote,
                    "branch": target_branch,
                }
            }
        },
    )

    err = _goto(app_layout.app_name)
    assert err == 0

    assert os.path.isdir(dep_path)

    dep_repo_after = git.Repo(dep_path)
    assert dep_repo_after.active_branch.name == target_branch
    assert dep_repo_after.head.commit.hexsha == expected_sha
    dep_repo_after.close()
