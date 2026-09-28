"""Auto-init on `vmn stamp` misjudged this repo on vmn_exp's first release:
the repo had no committed .vmn/conf.yml (it predates it) though .vmn/ held a
committed .gitignore and another app's state, so stamp re-ran `vmn init` —
which rewrote the customized .vmn/.gitignore — and the new app, whose
conf.yml was committed ahead of its first stamp, was taken for an initialized
one and refused ("Untracked app")."""
import os
import subprocess

from helpers import _init_app, _run_vmn_init, _stamp_app
from version_stamp.core.constants import INIT_COMMIT_MESSAGE

CUSTOM = "# kept by the user\nver.yml\n"


def _git(app_layout, *args):
    return subprocess.run(
        ["git", *args], cwd=app_layout.repo_path, check=True, capture_output=True, text=True
    ).stdout


def _gitignore(app_layout):
    with open(os.path.join(app_layout.repo_path, ".vmn", ".gitignore")) as f:
        return f.read()


def _init_commits(app_layout):
    return _git(app_layout, "log", "--format=%s").splitlines().count(INIT_COMMIT_MESSAGE)


def test_init_keeps_an_existing_gitignore(app_layout):
    # Not committed: a committed one already marks the repo initialized.
    app_layout.write_file_commit_and_push(
        "test_repo_0", ".vmn/.gitignore", CUSTOM, commit=False, push=False
    )
    assert _run_vmn_init() == 0
    content = _gitignore(app_layout)
    assert content.startswith(CUSTOM)
    assert "vmn.lock" in content.splitlines()


def test_init_adds_each_default_entry_once(app_layout):
    # Not committed: a committed one already marks the repo initialized.
    app_layout.write_file_commit_and_push(
        "test_repo_0", ".vmn/.gitignore", "vmn.lock\n", commit=False, push=False
    )
    assert _run_vmn_init() == 0
    assert _gitignore(app_layout).splitlines().count("vmn.lock") == 1


def test_stamp_a_new_app_in_a_repo_without_a_root_conf(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    # A repo from before .vmn/conf.yml: .vmn/.gitignore and app state only.
    _git(app_layout, "rm", "-q", ".vmn/conf.yml")
    _git(app_layout, "commit", "-q", "-m", "legacy layout")
    _git(app_layout, "push", "-q")
    with open(os.path.join(app_layout.repo_path, ".vmn", ".gitignore"), "a") as f:
        f.write(CUSTOM)
    _git(app_layout, "commit", "-q", "-am", "custom ignore")
    _git(app_layout, "push", "-q")
    inits = _init_commits(app_layout)

    err, ver_info, _ = _stamp_app("new_app", "minor")

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.1.0"
    assert _init_commits(app_layout) == inits
    assert CUSTOM in _gitignore(app_layout)


def test_stamp_a_new_app_whose_conf_was_committed_first(app_layout):
    _run_vmn_init()
    conf_path = os.path.join(app_layout.repo_path, ".vmn", "new_app", "conf.yml")
    os.makedirs(os.path.dirname(conf_path))
    app_layout.write_conf(conf_path, default_release_mode="patch")

    err, ver_info, _ = _stamp_app("new_app", "minor")

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.1.0"
