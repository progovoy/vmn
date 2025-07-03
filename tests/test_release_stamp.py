import os
import subprocess
from pathlib import Path
import sys
sys.path.append("{0}/../version_stamp".format(os.path.dirname(__file__)))
import pytest
import stamp_utils

from test_ver_stamp import _run_vmn_init, _init_app, _stamp_app

import release_stamp as rel


def test_happy_path_stamps_release(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")

    prev_commit = app_layout.git_cmd(args=["rev-parse", "HEAD"]).strip()
    cwd = os.getcwd()
    os.chdir(app_layout.repo_path)
    res = rel.main(["--stamp"])
    os.chdir(cwd)
    assert res == 0
    new_commit = app_layout.git_cmd(args=["rev-parse", "HEAD"]).strip()
    assert new_commit != prev_commit
    tags = app_layout.get_all_tags()
    expected_tag = f"{app_layout.app_name}_0.0.1"
    assert expected_tag in tags


def test_dry_run_does_not_change(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")

    prev_commit = app_layout.git_cmd(args=["rev-parse", "HEAD"]).strip()
    tags_before = set(app_layout.get_all_tags())
    cwd = os.getcwd()
    os.chdir(app_layout.repo_path)
    res = rel.main(["--stamp", "--dry-run"])
    os.chdir(cwd)
    assert res == 0
    new_commit = app_layout.git_cmd(args=["rev-parse", "HEAD"]).strip()
    assert new_commit == prev_commit
    assert set(app_layout.get_all_tags()) == tags_before


def test_push_failure_rolls_back(app_layout, monkeypatch):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")

    prev_commit = app_layout.git_cmd(args=["rev-parse", "HEAD"]).strip()
    tags_before = set(app_layout.get_all_tags())

    def boom(*a, **kw):
        raise RuntimeError("push failed")

    monkeypatch.setattr(rel, "atomic_push", boom)
    cwd = os.getcwd()
    os.chdir(app_layout.repo_path)
    res = rel.main(["--stamp"])
    os.chdir(cwd)
    assert res == 1
    new_commit = app_layout.git_cmd(args=["rev-parse", "HEAD"]).strip()
    assert new_commit == prev_commit
    assert set(app_layout.get_all_tags()) == tags_before


def test_branch_policy_violation(app_layout, monkeypatch):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")

    app_layout.checkout("feature", create_new=True)

    monkeypatch.setenv("RELEASE_BRANCHES", "main")
    cwd = os.getcwd()
    os.chdir(app_layout.repo_path)
    res = rel.main(["--stamp"])
    os.chdir(cwd)
    assert res == 1


@pytest.mark.parametrize("args", [["--stamp", "-v", "1.0.0"], ["--stamp", "--version", "1.0.0"]])
def test_flag_conflict(args):
    with pytest.raises(SystemExit):
        rel.main(args)
