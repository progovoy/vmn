"""``vmn stamp`` never writes a remote URL's credentials into a tag message,
and ``vmn goto`` cloning a dependency from such a cleaned URL borrows the
checkout's own remote credentials when the host is the same."""
import subprocess

import pytest
import yaml

from helpers import _bootstrap, _stamp_app
from version_stamp.core.utils import borrow_credentials

TOKEN = "glpat-SECRET"
TOKEN_URL = f"https://oauth2:{TOKEN}@gitlab.example.com/group/repo.git"
CLEAN_URL = "https://gitlab.example.com/group/repo.git"
DEP_URL = "https://gitlab.example.com/group/dep.git"


def _tag_message(repo_path, app_name):
    out = subprocess.run(
        ["git", "for-each-ref", "--sort=-creatordate", "--count=1",
         "--format=%(contents)", f"refs/tags/{app_name}_*"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    ).stdout
    return out


def test_stamp_writes_no_credentials_into_the_tag(app_layout, monkeypatch):
    from version_stamp.backends import git_history

    _bootstrap(app_layout)
    monkeypatch.setattr(git_history.GitHistoryMixin, "remote", lambda self: TOKEN_URL)
    app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "more\n")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    message = _tag_message(app_layout.repo_path, app_layout.app_name)
    assert TOKEN not in message
    changesets = yaml.safe_load(message)["stamping"]["app"]["changesets"]
    assert changesets["."]["remote"] == CLEAN_URL


@pytest.mark.parametrize(
    "url, donor, expected",
    [
        (DEP_URL, TOKEN_URL, f"https://oauth2:{TOKEN}@gitlab.example.com/group/dep.git"),
        ("HTTPS://GitLab.example.com/group/dep.git", TOKEN_URL,
         f"HTTPS://oauth2:{TOKEN}@GitLab.example.com/group/dep.git"),
        ("https://other.example.com/x.git", TOKEN_URL, "https://other.example.com/x.git"),
        ("http://gitlab.example.com/x.git", TOKEN_URL, "http://gitlab.example.com/x.git"),
        ("https://u:p@gitlab.example.com/x.git", TOKEN_URL, "https://u:p@gitlab.example.com/x.git"),
        (DEP_URL, CLEAN_URL, DEP_URL),
        (DEP_URL, None, DEP_URL),
        ("git@gitlab.example.com:group/dep.git", TOKEN_URL, "git@gitlab.example.com:group/dep.git"),
        ("ssh://git@gitlab.example.com/x.git", TOKEN_URL, "ssh://git@gitlab.example.com/x.git"),
        ("../dep", TOKEN_URL, "../dep"),
        (None, TOKEN_URL, None),
    ],
)
def test_borrow_credentials(url, donor, expected):
    assert borrow_credentials(url, donor) == expected


def test_goto_clones_a_dep_with_the_checkouts_credentials(tmp_path):
    from version_stamp.cli.output import _clone_args

    deps = {"../dep": {"remote": DEP_URL, "vcs_type": "git"},
            "../other": {"remote": "https://other.example.com/o.git", "vcs_type": "git"}}

    args = _clone_args(deps, str(tmp_path), TOKEN_URL)

    remotes = {rel: remote for _, rel, remote, _ in args}
    assert remotes["../dep"] == f"https://oauth2:{TOKEN}@gitlab.example.com/group/dep.git"
    assert remotes["../other"] == "https://other.example.com/o.git"
    assert deps["../dep"]["remote"] == DEP_URL
