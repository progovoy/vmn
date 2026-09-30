"""Version math scopes octet lookups to the app's own tags; "." deps come from
the open backend."""
import os
from unittest import mock

from git import Repo

from helpers import _init_app, _run_vmn_init, _stamp_app
from version_stamp.backends.git import GitBackend


def _commit_change(app_layout, name):
    repo_name = app_layout.repo_path.split(os.path.sep)[-1]
    app_layout.write_file_commit_and_push(repo_name, name, name)


def test_major_bump_ignores_apps_sharing_the_name_prefix(app_layout):
    _run_vmn_init()
    _init_app("foo", "1.0.0")
    _init_app("foo_bar", "2.0.0")
    _commit_change(app_layout, "f1.file")
    err, ver_info, _ = _stamp_app("foo_bar", "major")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "3.0.0"

    _commit_change(app_layout, "f2.file")
    err, ver_info, _ = _stamp_app("foo", "major")

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "2.0.0"


def test_minor_bump_after_later_hotfix_on_older_line(app_layout, capfd):
    _run_vmn_init()
    _init_app("foo", "1.0.0")
    _commit_change(app_layout, "f1.file")
    err, ver_info, _ = _stamp_app("foo", "minor")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "1.1.0"

    _commit_change(app_layout, "f2.file")
    err, ver_info, _ = _stamp_app("foo", "hotfix", override_version="1.0.0")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "1.0.0.1"

    _commit_change(app_layout, "f3.file")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app("foo", "minor")

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "1.2.0"
    assert "Failed to publish" not in capfd.readouterr().err


def test_main_repo_changeset_skips_get_repo_details(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _commit_change(app_layout, "f1.file")
    user_commit = Repo(app_layout.repo_path).head.commit.hexsha
    expected_remote = GitBackend.get_repo_details(app_layout.repo_path)[1]
    real = GitBackend.get_repo_details
    with mock.patch.object(
        GitBackend, "get_repo_details", side_effect=real
    ) as details:
        err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    assert err == 0
    assert ver_info["stamping"]["app"]["changesets"]["."] == {
        "hash": user_commit,
        "remote": expected_remote,
        "vcs_type": "git",
    }
    called = [os.path.normpath(c.args[0]) for c in details.call_args_list]
    assert os.path.normpath(app_layout.repo_path) not in called
