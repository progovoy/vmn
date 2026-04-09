import os
import subprocess

import pytest
import yaml

from version_stamp.cli.constants import VER_FILE_NAME

from helpers import (
    _init_app,
    _release_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


@pytest.mark.parametrize(
    "branch_name", [("new_branch", "new_branch2"), ("new_branch/a", "new_branch2/b")]
)
def test_change_of_tracking_branch(app_layout, capfd, branch_name):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    app_layout.checkout(branch_name[0], create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    app_layout.checkout(branch_name[1], create_new=True)

    app_layout.delete_branch(branch_name[0])

    app_layout._app_backend.be._be.git.branch(
        f"--set-upstream-to=origin/{branch_name[0]}", branch_name[1]
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="patch")
    assert err == 0


def test_missing_local_branch(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    cur_hex = app_layout._app_backend.be.changeset()
    app_layout.checkout(cur_hex)

    app_layout.delete_branch(main_branch)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_missing_local_branch_error_scenarios(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    main_branch = app_layout._app_backend.be.get_active_branch()
    cur_hex = app_layout._app_backend.be._be.head.commit.hexsha

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    app_layout.checkout(cur_hex)
    app_layout.delete_branch(main_branch)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 1

    cur_hex = app_layout._app_backend.be._be.head.commit.hexsha
    app_layout.checkout(cur_hex)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 1


def test_no_fetch_branch_configured(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    app_layout.git_cmd(args=["config", "--unset", "remote.origin.fetch"])

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0


def test_two_prs_from_same_origin(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    main_branch = app_layout._app_backend.be.get_active_branch()
    first_branch = "first"

    app_layout.checkout(first_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=first_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{first_branch}.1"
    assert data["prerelease"] == first_branch
    app_layout.checkout(main_branch, create_new=False)
    second_branch = "second"

    app_layout.checkout(second_branch, create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=second_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{second_branch}.1"
    assert data["prerelease"] == second_branch


def test_two_prs_from_same_origin_after_release(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    main_branch = app_layout._app_backend.be.get_active_branch()
    first_branch = "first"

    app_layout.checkout(first_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=first_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{first_branch}.1"
    assert data["prerelease"] == first_branch
    app_layout.checkout(main_branch, create_new=False)
    second_branch = "second"

    app_layout.checkout(second_branch, create_new=True)
    app_layout.checkout(main_branch)
    _release_app(app_layout.app_name, f"0.0.2-{first_branch}.1")
    app_layout.checkout(second_branch)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=second_branch
    )
    capfd.readouterr()
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.3-{second_branch}.1"
    assert data["prerelease"] == second_branch


def test_stamp_with_removed_tags_no_commit(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    ret, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ret == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_stamp_with_removed_tags_with_commit(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "a/b/c/f1.file", "msg1")

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    ret, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ret == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_show_after_1_tag_removed(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "a/b/c/f1.file", "msg1")

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "dirty:\n- version_not_matched\nout: 0.0.0\n\n" == captured.out


def test_show_after_multiple_tags_removed_1_tag_left(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    for i in range(4):
        app_layout.write_file_commit_and_push(
            "test_repo_0", "a/b/c/f1.file", f"{i}msg1"
        )
        _stamp_app(f"{app_layout.app_name}", "patch")
        app_layout.remove_tag(f"{app_layout.app_name}_0.0.{i + 1}")

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()

    res = yaml.safe_load(captured.out)
    assert res["out"] == "0.0.0"
    assert res["dirty"][0] == "version_not_matched"


def test_show_after_multiple_tags_removed_0_tags_left(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    app_layout.remove_tag(f"{app_layout.app_name}_0.0.0")

    for i in range(4):
        app_layout.write_file_commit_and_push(
            "test_repo_0", "a/b/c/f1.file", f"{i}msg1"
        )
        _stamp_app(f"{app_layout.app_name}", "patch")
        app_layout.remove_tag(f"{app_layout.app_name}_0.0.{i + 1}")

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 1

    captured = capfd.readouterr()
    assert (
        captured.err == "[ERROR] Failed to get version info for tag: test_app_0.0.0\n"
        "[ERROR] Untracked app. Run vmn init-app first\n"
        "[ERROR] Error occured when getting the repo status\n"
    )


def test_shallow_vmn_commit_repo_stamp(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_shallow_non_vmn_commit_repo_stamp(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "connnntenctt")

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    capfd.readouterr()
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_shallow_vmn_commit_repo_stamp_pr(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch", prerelease="yuval")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1-yuval.1"

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.tst",
        "bla",
    )

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1-yuval.2"


def test_shallow_removed_vmn_tag_repo_stamp(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


@pytest.mark.parametrize("manual_version", [("0.0.0", "0.0.1"), ("2.0.0", "2.0.1")])
def test_removed_vmn_tag_and_version_file_repo_stamp(app_layout, manual_version):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, params = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    file_path = params["version_file_path"]

    app_layout.remove_file(file_path)
    verfile_manual_content = {
        "version_to_stamp_from": manual_version[0],
        "prerelease": "release",
        "prerelease_count": {},
    }
    # now we want to override the version by changing the file version:
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        ".vmn/test_app/{}".format(VER_FILE_NAME),
        yaml.dump(verfile_manual_content),
    )

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == manual_version[1]


def test_same_user_tag(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.tst",
        "bla",
    )

    app_layout.create_tag("HEAD~3", f"{app_layout.app_name}_2.0.0")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_bad_tag(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    app_layout.create_tag("HEAD", "Semver-foo-python3-1.1.1")

    # read to clear stderr and out
    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    capfd.readouterr()

    assert err == 0

    app_layout.create_tag("HEAD", "app_name-1.1.1")

    # read to clear stderr and out
    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    capfd.readouterr()

    assert err == 0


def test_jenkins_checkout(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    main_branch = app_layout._app_backend.be.get_active_branch()
    app_layout.checkout("new_branch", create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    app_layout.checkout_jekins(main_branch)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_jenkins_checkout_branch_name_order_edge_case(app_layout, capfd):
    # When running in jenkins repo, the remote branch gets deleted.
    # Vmn tries to find to correct remote brach using the command "git branch -r HEAD".
    # It returns a list, and we must choose the right branch, not just the first of the list.
    # The following test creates a branch with a name above 'master' alphabetically,
    # And we should still choose master as our rightful remote
    _run_vmn_init()
    _init_app(app_layout.app_name)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    main_branch = app_layout._app_backend.be.get_active_branch()
    app_layout.checkout(
        "a_branch", create_new=True
    )  # The name of the branch is critical because it affect "git branch -r HEAD" list order

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg3")
    app_layout.checkout_jekins(main_branch)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
