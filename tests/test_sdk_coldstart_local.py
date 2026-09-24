"""An SDK cold start is local-only: it never pushes.

``start_run()`` in a fresh repo inits vmn and stamps a ``0.0.0`` baseline. It used
to push that commit and tag as a side effect of a training script (surprising
with a remote) and to crash without one (``No git remote is configured``).
"""
import os
import subprocess

import pytest
from helpers import _storage

from version_stamp.exp import start_run


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def _remote_refs(app_layout):
    return _git(app_layout.repo_path, "ls-remote", "origin")


def test_cold_start_without_a_remote_succeeds_locally(app_layout):
    _git(app_layout.repo_path, "remote", "remove", "origin")

    with start_run(app_layout.app_name) as run:
        run.log_metric("acc", 0.5)

    assert run.id.startswith("0.0.0-dev.")
    assert f"{app_layout.app_name}_0.0.0" in _git(app_layout.repo_path, "tag")
    metas = _storage(app_layout).list_snapshots(app_layout.app_name)
    assert [m["verstr"] for m in metas] == [run.id]


def test_cold_start_with_a_remote_pushes_nothing(app_layout):
    before = _remote_refs(app_layout)

    with start_run(app_layout.app_name) as run:
        pass

    assert _remote_refs(app_layout) == before
    assert f"{app_layout.app_name}_0.0.0" in _git(app_layout.repo_path, "tag")
    assert os.path.isfile(os.path.join(app_layout.repo_path, ".vmn", "conf.yml"))

    with start_run(app_layout.app_name) as second:
        pass
    assert second.id != run.id
    assert _remote_refs(app_layout) == before
