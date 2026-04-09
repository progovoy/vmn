import os

import pytest
import yaml

from helpers import _init_app, _release_app, _run_vmn_init, _show, _stamp_app


def test_double_release_works(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    captured = capfd.readouterr()
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.2"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="beta")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.1"
    assert data["prerelease"] == "beta"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.2"
    assert data["prerelease"] == "beta"

    for i in range(2):
        capfd.readouterr()
        err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-beta.2")
        captured = capfd.readouterr()

        assert err == 0
        assert captured.out == "[INFO] 1.3.0\n"
        assert captured.err == ""

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0")
    captured = capfd.readouterr()

    assert err == 0
    assert captured.out == "[INFO] 1.3.0\n"
    assert captured.err == ""

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-beta.1")
    captured = capfd.readouterr()

    assert err == 1
    assert captured.err == "[ERROR] Failed to release 1.3.0-beta.1\n"
    assert captured.out == ""

    err, ver_info, _ = _release_app(app_layout.app_name)
    captured = capfd.readouterr()

    assert err == 0
    assert captured.out == "[INFO] 1.3.0\n"
    assert captured.err == ""

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg2")
    err, ver_info, _ = _release_app(app_layout.app_name)
    captured = capfd.readouterr()

    assert err == 1
    assert captured.out == ""
    assert (
        captured.err == "[ERROR] When running vmn release and not on a version commit, "
        "you must specify a specific version using -v flag or use --stamp\n"
    )


def test_release_with_stamp_creates_commit(app_layout, capfd):
    """Test that vmn release --stamp creates a new commit with version files."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    # Create prerelease
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1-rc.1"
    prerelease_commit = app_layout._app_backend.be.changeset()

    # Release with --stamp
    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, stamp=True)
    captured = capfd.readouterr()

    assert err == 0
    assert captured.out == "[INFO] 0.0.1\n"
    assert captured.err == ""

    # Verify new commit was created
    release_commit = app_layout._app_backend.be.changeset()
    assert release_commit != prerelease_commit

    # Verify version info
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"
    assert data["prerelease"] == "release"


def test_release_with_stamp_detached_head_fails(app_layout, capfd):
    """Test that vmn release --stamp fails in detached HEAD state."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    # Create prerelease
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="patch", prerelease="rc"
    )
    assert err == 0

    # Detach HEAD
    app_layout._app_backend.be._be.git.checkout("--detach")

    # Try release with --stamp - should fail
    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, stamp=True)
    captured = capfd.readouterr()

    assert err == 1
    assert captured.err == "[ERROR] Cannot use --stamp in detached HEAD state\n"


def test_release_with_stamp_from_release_version_fails(app_layout, capfd):
    """Test that vmn release --stamp fails when already on a release version."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    # Create a release version (not prerelease)
    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"

    # Try release with --stamp - should fail
    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, stamp=True)
    captured = capfd.readouterr()

    assert err == 1
    assert "Cannot use --stamp to release 0.0.1" in captured.err
    assert "Version must be a prerelease" in captured.err


def test_release_with_stamp_fails_when_not_on_version_commit(app_layout, capfd):
    """Test that vmn release --stamp fails when not on the latest RC.

    Scenario: User creates rc.1, then rc.2, then makes more commits and tries
    to release with --stamp. This should fail because the user is not on a
    version commit (HEAD doesn't match any version).
    """
    _run_vmn_init()
    _init_app(app_layout.app_name)

    # Create rc.1
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="patch", prerelease="rc"
    )
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1-rc.1"

    # Create rc.2 (new commit + stamp)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1-rc.2"

    # Make another commit after rc.2
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")

    # Now we're not on any version commit
    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, stamp=True)
    captured = capfd.readouterr()

    assert err == 1
    assert "Cannot use --stamp when not on a version commit" in captured.err


def test_no_pr_happens_after_release(app_layout, capfd):
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
    app_layout.checkout(main_branch)
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

    app_layout.checkout(main_branch)
    app_layout.merge(from_rev=second_branch, to_rev=main_branch)

    err, ver_info, _ = _release_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"
    assert data["prerelease"] == "release"

    third_branch = "third"
    app_layout.checkout(third_branch, create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=third_branch
    )
    captured = capfd.readouterr()
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.3-{third_branch}.1"

    app_layout.checkout(first_branch)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=first_branch
    )
    captured = capfd.readouterr()
    assert (
        captured.err
        == "[ERROR] The version 0.0.2 was already released. Will refuse to stamp prerelease version\n"
    )
    assert err == 1


def test_rc_after_release(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.1"
    assert data["prerelease"] == "rc"

    i = 0
    for i in range(5):
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")

        data = ver_info["stamping"]["app"]
        assert data["_version"] == f"1.3.0-rc.{i + 2}"
        assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-rc.2")
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    captured = capfd.readouterr()
    assert err != 0
    assert captured.err.startswith("[ERROR] The version 1.3.0 was already ")

    app_layout._app_backend.be._be.delete_tag("test_app_1.3.0")

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"1.3.0-rc.{i + 2 + 1}"
    assert data["prerelease"] == "rc"

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-rc.3")
    captured = capfd.readouterr()
    assert err == 1

    app_layout.pull(tags=True)

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-rc.3")
    captured = capfd.readouterr()
    assert err == 1

    err = _show(app_layout.app_name, version="1.3.0", verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert "1.3.0-rc.2" in tmp["versions"]


def test_release_branch_policy(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "text")

    conf = {
        "policies": {"whitelist_release_branches": ["main", "master"]},
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    main_branch = app_layout._app_backend.be.get_active_branch()
    app_layout.checkout("new_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1

    captured = capfd.readouterr()
    assert (
        captured.err
        == "[ERROR] Policy: whitelist_release_branches was violated. Refusing to stamp\n"
    )

    capfd.readouterr()
    err, ver_info, params = _stamp_app(
        app_layout.app_name, "patch", prerelease="staging"
    )
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg2")

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, version="0.0.3-staging.1")
    assert err == 1
    captured = capfd.readouterr()
    assert captured.err.startswith(
        "[ERROR] Policy: whitelist_release_branches was violated. Refusing to release"
    )

    app_layout.checkout(main_branch)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg2")

    capfd.readouterr()
    err, ver_info, params = _stamp_app(
        app_layout.app_name, "patch", prerelease="staging"
    )
    assert err == 0

    err, ver_info, _ = _release_app(app_layout.app_name, version="0.0.3-staging.1")
    assert err == 1

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name)
    captured = capfd.readouterr()
    assert err == 0


def test_backward_compatability_with_0_8_4_vmn(app_layout, capfd):
    app_layout.stamp_with_previous_vmn("0.8.4")

    capfd.readouterr()
    err = _show("app1", verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)

    assert "1.0.0-alpha1" == tmp["version"]

    err = _show("app1", verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert "1.0.0-alpha1" == tmp["version"]
