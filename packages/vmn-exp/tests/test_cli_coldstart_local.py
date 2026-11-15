"""`vmn-exp create`'s cold start works without a remote and announces what it
commits, tags and pushes (mirrors test_sdk_coldstart_local.py for the CLI)."""
import subprocess

import pytest
from exp_helpers import _experiment


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def test_cli_cold_start_without_a_remote_succeeds_and_tags_locally(app_layout, capfd):
    _git(app_layout.repo_path, "remote", "remove", "origin")
    capfd.readouterr()

    assert _experiment(app_layout.app_name, action="create") == 0

    assert f"{app_layout.app_name}_0.0.0" in _git(app_layout.repo_path, "tag")
    out = "".join(capfd.readouterr())
    assert "Nothing is pushed" in out


def test_cli_cold_start_with_a_remote_announces_the_push(app_layout, capfd):
    before = _git(app_layout.repo_path, "ls-remote", "origin")
    capfd.readouterr()

    assert _experiment(app_layout.app_name, action="create") == 0

    out = "".join(capfd.readouterr())
    assert f"{app_layout.app_name}_0.0.0" in out
    assert "pushed to origin" in out
    assert _git(app_layout.repo_path, "ls-remote", "origin") != before
