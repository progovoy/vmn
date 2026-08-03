"""Tests for forward compatibility with old vmn versions and config formats.

Covers:
- vmn 0.3.9 tag format (tag_format_039)
- vmn 0.8.5rc2 prerelease handling
- release_mode_policy migration from nested config (config_keys)
- legacy top-level default_release_mode as policy (config_keys)
"""
import pytest
import yaml

from helpers import _goto, _init_app, _run_vmn_init, _show, _stamp_app


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


def test_release_mode_policy_migration_from_nested(app_layout, capfd):
    """Old nested conventional_commits.default_release_mode auto-migrates to release_mode_policy."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Write old-style nested config manually
    with open(params["app_conf_path"], "w") as f:
        yaml.dump(
            {
                "conf": {
                    "conventional_commits": {"default_release_mode": "strict"},
                }
            },
            f,
        )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="fix: something"
    )
    # Commit conf change so repo is clean
    app_layout.git_cmd(args=["add", params["app_conf_path"]])
    app_layout.git_cmd(args=["commit", "-m", "update conf"])
    app_layout.git_cmd(args=["push"])

    # Should auto-migrate and work (strict mode -> acts like -r)
    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"


def test_legacy_top_level_default_release_mode_as_policy(app_layout, capfd):
    """Old top-level default_release_mode: optional/strict is treated as release_mode_policy."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Write config using old field name with policy value
    with open(params["app_conf_path"], "w") as f:
        yaml.dump(
            {
                "conf": {
                    "conventional_commits": True,
                    "default_release_mode": "strict",
                }
            },
            f,
        )

    app_layout.git_cmd(args=["add", params["app_conf_path"]])
    app_layout.git_cmd(args=["commit", "-m", "update conf"])
    app_layout.git_cmd(args=["push"])

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="fix: something"
    )

    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"
