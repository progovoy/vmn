"""A run's ``author`` (core/identity.py ``run_author``): this host's identity
with its values stripped and empty ones dropped, plus ``source`` naming where
``git_user_email`` came from — git config in the given directory, else the
first of the caller's fallbacks that has one (``VMN_EXP_AUTHOR``, a local
commit's ``From:``, an exporter's email), else ``host``."""
import subprocess

import pytest
from vmn_exp.core import identity
from vmn_exp.core import writer as experiment_writer


@pytest.fixture(autouse=True)
def _host(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "gpu-07")
    monkeypatch.setenv("USER", "alice")
    monkeypatch.delenv(identity.AUTHOR_ENV, raising=False)
    experiment_writer._WRITER_ID = None


@pytest.fixture
def no_git_email(monkeypatch):
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "")


def _repo_with_email(path, email):
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", email], cwd=path, check=True)
    return str(path)


def test_the_author_env_var_is_vmn_exp_author():
    assert identity.AUTHOR_ENV == "VMN_EXP_AUTHOR"


def test_git_config_in_the_given_directory_wins_over_every_fallback(tmp_path):
    repo = _repo_with_email(tmp_path / "repo", "a@x.io")
    author = identity.run_author(repo, [("env", "e@x.io"), ("commit", "c@x.io")])
    assert author == {"writer": "gpu-07", "git_user_email": "a@x.io",
                      "os_user": "alice", "source": "git"}


def test_without_a_git_email_the_first_fallback_with_one_wins(no_git_email):
    author = identity.run_author(None, [("env", "  "), ("commit", " c@x.io\n"),
                                        ("export", "x@x.io")])
    assert author["git_user_email"] == "c@x.io"
    assert author["source"] == "commit"


def test_fallbacks_without_an_email_leave_the_host_as_the_source(no_git_email):
    author = identity.run_author(None, [("env", ""), ("commit", None)])
    assert author == {"writer": "gpu-07", "os_user": "alice", "source": "host"}


def test_identity_values_are_stripped_and_empty_ones_dropped(no_git_email, monkeypatch):
    monkeypatch.setattr(identity, "_os_user", lambda: "  ")
    monkeypatch.setenv("VMN_WRITER_ID", " gpu-07 ")
    experiment_writer._WRITER_ID = None
    assert identity.run_author(None, [("env", " e@x.io ")]) == {
        "writer": "gpu-07", "git_user_email": "e@x.io", "source": "env"}


def test_known_identity_is_actor_identity_without_empty_values(no_git_email):
    assert identity.known_identity() == {"writer": "gpu-07", "os_user": "alice"}


def test_env_author_is_the_vmn_exp_author_fallback(monkeypatch):
    assert identity.env_author() == ("env", "")
    monkeypatch.setenv("VMN_EXP_AUTHOR", "bob@x.io")
    assert identity.env_author() == ("env", "bob@x.io")
