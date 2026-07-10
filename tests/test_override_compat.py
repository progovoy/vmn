import os
import subprocess

import pytest
import yaml

from helpers import _goto, _init_app, _release_app, _run_vmn_init, _show, _stamp_app


def test_overwrite_version_and_orm(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    main_branch = app_layout._app_backend.be.get_active_branch()
    c1_branch = "c1"
    app_layout.checkout(c1_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="patch", prerelease=c1_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{c1_branch}.1"
    assert data["prerelease"] == c1_branch

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        optional_release_mode="patch",
        prerelease=c1_branch,
        override_version="0.1.0",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.1.1-{c1_branch}.1"
    assert data["prerelease"] == c1_branch
    app_layout.checkout(main_branch, create_new=False)


def test_override_version(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        optional_release_mode="patch",
        prerelease="rc",
        override_version="0.1.0",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]

    assert data["_version"] == "0.1.1-rc.1"


def test_merge_version_conflict(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    # 0.0.1
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.checkout(main_branch, create_new=True)
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="ab"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-ab.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="ac"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-ac.1"

    app_layout.merge(from_rev="first_branch", to_rev="second_branch")
    pass


def test_orm_use_override_in_rc(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="1.0.0",
        optional_release_mode="patch",
        prerelease="rc",
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1-rc.1"
    assert data["prerelease"] == "rc"


def test_orm_use_override_rc_in_rc(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="1.0.1-rc.1",
        optional_release_mode="patch",
        prerelease="rc",
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_use_override_diff_rc_in_rc(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="1.0.1-rc1.1",
        optional_release_mode="patch",
        prerelease="rc2",
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1-rc2.1"
    assert data["prerelease"] == "rc2"


def test_orm_use_override_in_stable(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, "patch", override_version="1.0.0"
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1"


def test_overwrite_with_orm_from_orm(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-staging.1"
    assert data["prerelease"] == "staging"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="0.0.3-staging.1",
        optional_release_mode="patch",
        prerelease="staging",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.3-staging.2"
    assert data["prerelease"] == "staging"


def test_overwrite_with_orm_from_stable(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-staging.1"
    assert data["prerelease"] == "staging"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-staging.2"
    assert data["prerelease"] == "staging"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="0.0.2",
        optional_release_mode="patch",
        prerelease="staging",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.3-staging.1"
    assert data["prerelease"] == "staging"


def test_backward_compatability_with_0_3_9_vmn(app_layout, capfd):
    app_layout.stamp_with_previous_vmn("0.3.9")

    capfd.readouterr()
    err, ver_info, _ = _stamp_app("app1", "major")
    captured = capfd.readouterr()
    assert err == 0
    assert (
        "[INFO] Found existing version 0.0.3 and nothing has changed. Will not stamp\n"
        == captured.out
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app("app1", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.4"

    err = _goto("app1", version="0.0.2")
    assert err == 0

    err = _goto("app1", version="0.0.3")
    assert err == 0

    err = _goto("app1", version="0.0.4")
    assert err == 0

    err = _goto("app1")
    assert err == 0

    err, ver_info, _ = _stamp_app("root_app/service1", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_problem_found_in_real_customer(app_layout, capfd):
    app_layout.stamp_with_previous_vmn("0.8.5rc2")

    err, ver_info, _ = _stamp_app(
        "app1", optional_release_mode="patch", prerelease="189."
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "2.3.2-189.1"
    assert data["prerelease"] == "189"


@pytest.mark.parametrize("default_release_mode,separate,first_commit_msg,first_expected_version,second_commit_msg,second_expected_version",
                         [
                             # Simple recognize release
                             ("", False, "fix: a", "0.0.2-staging.1", None, None),
                             ("", False, "feat: a", "0.1.0-staging.1", None, None),
                             ("", False, "BREAKING CHANGE: a", "1.0.0-staging.1", None, None),
                             ("", False, "fix!: a", "1.0.0-staging.1", None, None),
                             # Simple recognize optional release
                             ("optional", False, "fix: a", "0.0.2-staging.1", None, None),
                             ("optional", False, "feat: a", "0.1.0-staging.1", None, None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", None, None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", None, None),
                             # Recognize release same version types
                             ("", False, "fix: a", "0.0.2-staging.1", "fix: a", None),
                             ("", False, "feat: a", "0.1.0-staging.1", "feat: a", None),
                             ("", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("", False, "fix!: a", "1.0.0-staging.1", "fix!: a", None),
                             # Recognize optional release same version types
                             ("optional", False, "fix: a", "0.0.2-staging.1", "fix: a", None),
                             ("optional", False, "feat: a", "0.1.0-staging.1", "feat: a", None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", "fix!: a", None),
                             # Recognize release different version types
                             ("", False, "fix: a", "0.1.0-staging.1", "feat: a", None),
                             ("", False, "feat: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", None),
                             ("", False, "fix!: a", "1.0.0-staging.1", "fix: a", None),
                             # Recognize optional release different version types
                             ("optional", False, "fix: a", "0.1.0-staging.1", "feat: a", None),
                             ("optional", False, "feat: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", "fix: a", None),
                             # Recognize release same version types
                             ("", True, "fix: a", "0.0.2-staging.1", "fix: a", "0.0.3-staging.1"),
                             ("", True, "feat: a", "0.1.0-staging.1", "feat: a", "0.2.0-staging.1"),
                             ("", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", "2.0.0-staging.1"),
                             ("", True, "fix!: a", "1.0.0-staging.1", "fix!: a", "2.0.0-staging.1"),
                             # Recognize optional release same version types
                             ("optional", True, "fix: a", "0.0.2-staging.1", "fix: a", "0.0.2-staging.2"),
                             ("optional", True, "feat: a", "0.1.0-staging.1", "feat: a", "0.1.0-staging.2"),
                             ("optional", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", "1.0.0-staging.2"),
                             ("optional", True, "fix!: a", "1.0.0-staging.1", "fix!: a", "1.0.0-staging.2"),
                             # Recognize release different version types
                             ("", True, "fix: a", "0.0.2-staging.1", "feat: a", "0.1.0-staging.1"),
                             ("", True, "feat: a", "0.1.0-staging.1", "BREAKING CHANGE: a", "1.0.0-staging.1"),
                             ("", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", "2.0.0-staging.1"),
                             ("", True, "fix!: a", "1.0.0-staging.1", "fix: a", "1.0.1-staging.1"),
                             # Recognize optional release different version types
                             ("optional", True, "fix: a", "0.0.2-staging.1", "feat: a", "0.0.2-staging.2"),
                             ("optional", True, "feat: a", "0.1.0-staging.1", "BREAKING CHANGE: a", "0.1.0-staging.2"),
                             ("optional", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", "1.0.0-staging.2"),
                             ("optional", True, "fix!: a", "1.0.0-staging.1", "fix: a", "1.0.0-staging.2"),
                          ])
def test_conventional_commits(app_layout, capfd, default_release_mode, separate, first_commit_msg, first_expected_version, second_commit_msg, second_expected_version):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        default_release_mode=default_release_mode,
    )

    first_commit_msg += """prevent racing of requests

    Introduce a request id and a reference to latest request. Dismiss
    incoming responses other than from latest request.

    Remove timeouts which were used to mitigate the racing issue but are
    obsolete now.

    Reviewed-by: Z
    Refs: #123
        """

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg=first_commit_msg
    )

    if second_commit_msg is not None:
        second_commit_msg += """prevent racing of requests

                    Introduce a request id and a reference to latest request. Dismiss
                    incoming responses other than from latest request.

                    Remove timeouts which were used to mitigate the racing issue but are
                    obsolete now.

                    Reviewed-by: Z
                    Refs: #123
                        """

        if not separate:
            app_layout.write_file_commit_and_push(
                "test_repo_0", "f1.txt", "text", commit_msg=second_commit_msg
            )

    err, ver_info, params = _stamp_app(app_layout.app_name, prerelease="staging")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == first_expected_version
    assert data["prerelease"] == "staging"

    if second_commit_msg is None or not separate:
        return

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg=second_commit_msg
    )

    err, ver_info, params = _stamp_app(app_layout.app_name, prerelease="staging")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == second_expected_version
    assert data["prerelease"] == "staging"

@pytest.mark.parametrize("default_release_mode", ["","optional",])
def test_conventional_commits_simple_failure(app_layout, capfd, default_release_mode):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        default_release_mode=default_release_mode,
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="doc: a"
    )

    err, ver_info, params = _stamp_app(app_layout.app_name, prerelease="staging")
    assert err == 1
    captured = capfd.readouterr()
    assert (
        "[ERROR] When not in release candidate mode, a release mode must be "
        "specified - use -r/--release-mode with one of major/minor/patch/hotfix\n"
        == captured.err
    )

@pytest.mark.parametrize("default_release_mode", ["","optional",])
def test_conventional_commits_simple_overwrite(app_layout, capfd, default_release_mode):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        default_release_mode=default_release_mode,
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="fix: a"
    )

    err, ver_info, params = _stamp_app(
        app_layout.app_name, "minor", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0-staging.1"
    assert data["prerelease"] == "staging"
