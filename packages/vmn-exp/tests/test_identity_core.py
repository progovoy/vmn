"""Actor identity lives in core (core/identity.py); the registry re-exports it."""
import ast
import os
import pathlib
import subprocess

from vmn_exp.core import identity
from vmn_exp.core import writer as experiment_writer
from vmn_exp.registry import log as registry_log


def _repo_with_email(path, email):
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", email], cwd=path, check=True)
    return path


def test_the_registry_re_exports_the_core_helpers():
    assert registry_log.actor_identity is identity.actor_identity
    assert registry_log._git_user_email is identity._git_user_email
    assert registry_log._os_user is identity._os_user


def test_core_identity_does_not_import_the_registry():
    tree = ast.parse(pathlib.Path(identity.__file__).read_text())
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imported += [a.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for a in node.names]
    assert not [m for m in imported if m and m.startswith("vmn_exp.registry")]


def test_git_user_email_reads_the_config_of_the_given_directory(tmp_path):
    repo = _repo_with_email(tmp_path / "repo", "local@x.io")
    assert identity._git_user_email(cwd=str(repo)) == "local@x.io"


def test_git_user_email_is_empty_when_git_cannot_run_there(tmp_path):
    assert identity._git_user_email(cwd=str(tmp_path / "missing")) == ""


def test_git_user_email_is_empty_when_no_email_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert identity._git_user_email(cwd=str(tmp_path)) == ""


def test_actor_identity_combines_writer_email_and_os_user(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "gpu-07")
    monkeypatch.setenv("USER", "alice")
    experiment_writer._WRITER_ID = None
    repo = _repo_with_email(tmp_path / "repo", "a@x.io")
    assert identity.actor_identity(cwd=str(repo)) == {
        "writer": "gpu-07", "git_user_email": "a@x.io", "os_user": "alice"}


def test_actor_identity_defaults_to_the_process_cwd(tmp_path, monkeypatch):
    repo = _repo_with_email(tmp_path / "repo", "cwd@x.io")
    monkeypatch.chdir(repo)
    assert identity.actor_identity()["git_user_email"] == "cwd@x.io"
    assert registry_log.actor_identity()["git_user_email"] == "cwd@x.io"


def test_os_user_falls_back_through_the_env_vars(monkeypatch):
    for key in ("USER", "LOGNAME", "USERNAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOGNAME", "bob")
    assert identity._os_user() == "bob"
