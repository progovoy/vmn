"""GitBackend tag lookups: consistent return types and root-app tag names."""
import os
import subprocess

from helpers import _init_app, _run_vmn_init, _stamp_app
from island_helpers import _out
from version_stamp.backends.git import GitBackend


def _stamped_backend(app_layout, app_name):
    _run_vmn_init()
    _init_app(app_name)
    assert _stamp_app(app_name, "patch")[0] == 0
    return GitBackend(app_layout.repo_path)


def test_brother_tags_of_missing_tag_is_empty_dict(app_layout):
    backend = _stamped_backend(app_layout, app_layout.app_name)

    assert backend.get_all_brother_tags("no_such_app_9.9.9") == {}


def test_tag_version_info_of_non_vmn_tag_on_vmn_commit_is_empty_dict(app_layout):
    backend = _stamped_backend(app_layout, app_layout.app_name)
    _out(app_layout.repo_path, "tag", "-a", "other_9.9.9", "-m", "not vmn")

    assert backend.get_tag_version_info("other_9.9.9") == ("other_9.9.9", {})


def _recommit_head_without_tags(repo_path):
    env = dict(os.environ, GIT_COMMITTER_DATE="2001-01-01T00:00:00")
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-q", "--amend", "--no-edit"],
        check=True,
        env=env,
    )
    return _out(repo_path, "rev-parse", "HEAD")


def test_rebased_root_app_commit_recovers_its_tags(app_layout):
    app_name = "root_app/service1"
    backend = _stamped_backend(app_layout, app_name)
    new_hex = _recommit_head_without_tags(app_layout.repo_path)

    ver_infos = backend.get_all_commit_tags_log_impl(new_hex, [], app_name)

    assert "root_app-service1_0.0.1" in ver_infos
    assert "root_app_1" in ver_infos
