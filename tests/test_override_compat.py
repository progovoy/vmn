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



# Tests for 0.3.9 / 0.8.5rc2 compat moved to tests/compat/test_version_compat.py



@pytest.mark.parametrize("release_mode_policy,separate,first_commit_msg,first_expected_version,second_commit_msg,second_expected_version",
                         [
                             # Simple recognize release
                             ("strict", False, "fix: a", "0.0.2-staging.1", None, None),
                             ("strict", False, "feat: a", "0.1.0-staging.1", None, None),
                             ("strict", False, "BREAKING CHANGE: a", "1.0.0-staging.1", None, None),
                             ("strict", False, "fix!: a", "1.0.0-staging.1", None, None),
                             # Simple recognize optional release
                             ("optional", False, "fix: a", "0.0.2-staging.1", None, None),
                             ("optional", False, "feat: a", "0.1.0-staging.1", None, None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", None, None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", None, None),
                             # Recognize release same version types
                             ("strict", False, "fix: a", "0.0.2-staging.1", "fix: a", None),
                             ("strict", False, "feat: a", "0.1.0-staging.1", "feat: a", None),
                             ("strict", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("strict", False, "fix!: a", "1.0.0-staging.1", "fix!: a", None),
                             # Recognize optional release same version types
                             ("optional", False, "fix: a", "0.0.2-staging.1", "fix: a", None),
                             ("optional", False, "feat: a", "0.1.0-staging.1", "feat: a", None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", "fix!: a", None),
                             # Recognize release different version types
                             ("strict", False, "fix: a", "0.1.0-staging.1", "feat: a", None),
                             ("strict", False, "feat: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("strict", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", None),
                             ("strict", False, "fix!: a", "1.0.0-staging.1", "fix: a", None),
                             # Recognize optional release different version types
                             ("optional", False, "fix: a", "0.1.0-staging.1", "feat: a", None),
                             ("optional", False, "feat: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", "fix: a", None),
                             # Recognize release same version types
                             ("strict", True, "fix: a", "0.0.2-staging.1", "fix: a", "0.0.3-staging.1"),
                             ("strict", True, "feat: a", "0.1.0-staging.1", "feat: a", "0.2.0-staging.1"),
                             ("strict", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", "2.0.0-staging.1"),
                             ("strict", True, "fix!: a", "1.0.0-staging.1", "fix!: a", "2.0.0-staging.1"),
                             # Recognize optional release same version types
                             ("optional", True, "fix: a", "0.0.2-staging.1", "fix: a", "0.0.2-staging.2"),
                             ("optional", True, "feat: a", "0.1.0-staging.1", "feat: a", "0.1.0-staging.2"),
                             ("optional", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", "1.0.0-staging.2"),
                             ("optional", True, "fix!: a", "1.0.0-staging.1", "fix!: a", "1.0.0-staging.2"),
                             # Recognize release different version types
                             ("strict", True, "fix: a", "0.0.2-staging.1", "feat: a", "0.1.0-staging.1"),
                             ("strict", True, "feat: a", "0.1.0-staging.1", "BREAKING CHANGE: a", "1.0.0-staging.1"),
                             ("strict", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", "2.0.0-staging.1"),
                             ("strict", True, "fix!: a", "1.0.0-staging.1", "fix: a", "1.0.1-staging.1"),
                             # Recognize optional release different version types
                             ("optional", True, "fix: a", "0.0.2-staging.1", "feat: a", "0.0.2-staging.2"),
                             ("optional", True, "feat: a", "0.1.0-staging.1", "BREAKING CHANGE: a", "0.1.0-staging.2"),
                             ("optional", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", "1.0.0-staging.2"),
                             ("optional", True, "fix!: a", "1.0.0-staging.1", "fix: a", "1.0.0-staging.2"),
                          ])
def test_conventional_commits(app_layout, capfd, release_mode_policy, separate, first_commit_msg, first_expected_version, second_commit_msg, second_expected_version):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        release_mode_policy=release_mode_policy,
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

@pytest.mark.parametrize("release_mode_policy", ["strict","optional",])
def test_conventional_commits_simple_failure(app_layout, capfd, release_mode_policy):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        release_mode_policy=release_mode_policy,
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

@pytest.mark.parametrize("release_mode_policy", ["strict","optional",])
def test_conventional_commits_simple_overwrite(app_layout, capfd, release_mode_policy):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        release_mode_policy=release_mode_policy,
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


@pytest.mark.parametrize(
    "fallback,policy,expected_version",
    [
        # fallback with strict policy (acts like -r)
        ("patch", "strict", "0.0.2"),
        ("minor", "strict", "0.1.0"),
        ("major", "strict", "1.0.0"),
        # fallback with optional policy (acts like --orm)
        ("patch", "optional", "0.0.2"),
        ("minor", "optional", "0.1.0"),
    ],
)
def test_default_release_mode_fallback(
    app_layout, capfd, fallback, policy, expected_version
):
    """default_release_mode provides a fallback when no -r and no conv commits detected."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        release_mode_policy=policy,
        default_release_mode=fallback,
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="no conventional format here"
    )

    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == expected_version


def test_default_release_mode_fallback_with_conv_commits(app_layout, capfd):
    """When conv commits find a mode, fallback is not used."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        release_mode_policy="strict",
        default_release_mode="patch",
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="feat: new feature"
    )

    # conv commits detect "minor" which overrides the "patch" fallback
    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0"


def test_default_release_mode_fallback_no_conv_commits_enabled(app_layout, capfd):
    """Fallback works even without conventional_commits enabled."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=False,
        release_mode_policy="strict",
        default_release_mode="minor",
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="whatever"
    )

    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0"


def _truncate_vmn_log(app_layout):
    open(_vmn_log_path(app_layout), "w").close()


def _vmn_log_path(app_layout):
    return os.path.join(app_layout.repo_path, ".vmn", "vmn.log")


def _read_vmn_log(app_layout):
    with open(_vmn_log_path(app_layout)) as f:
        return f.read()


def test_release_mode_reason_logged_for_conventional_commits(app_layout, capfd):
    """The log explains that the mode came from a specific conventional commit."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        release_mode_policy="strict",
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="feat: shiny new thing"
    )

    _truncate_vmn_log(app_layout)
    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.1.0"

    log = _read_vmn_log(app_layout)
    assert "Release mode 'minor' chosen because conventional commit" in log
    assert "feat: shiny new thing" in log
    assert "release_mode_policy=strict" in log


def test_release_mode_reason_logged_for_default_fallback(app_layout, capfd):
    """The log explains that the mode came from the configured fallback."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_conf(
        params["app_conf_path"],
        conventional_commits=True,
        release_mode_policy="optional",
        default_release_mode="patch",
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="no conventional format here"
    )

    _truncate_vmn_log(app_layout)
    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"

    log = _read_vmn_log(app_layout)
    assert "no commit since" in log
    assert (
        "Release mode 'patch' chosen because it is the configured "
        "default_release_mode" in log
    )
    assert "release_mode_policy=optional" in log


def test_release_mode_reason_logged_for_cli_flag(app_layout, capfd):
    """The log explains that the mode came from the command line."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    _truncate_vmn_log(app_layout)
    err, ver_info, params = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    log = _read_vmn_log(app_layout)
    assert "Release mode 'minor' chosen because it was given on the command line" in log


# Config migration tests moved to tests/compat/test_version_compat.py
