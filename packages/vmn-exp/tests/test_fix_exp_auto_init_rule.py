"""`vmn-exp` and the SDK auto-init by vmn's own rule for "initialized".

A repo is initialized once its .vmn/conf.yml *or* .vmn/.gitignore is committed
(repos from before the conf.yml existed have only the .gitignore); an app once
its version file is committed — a committed conf.yml alone does not count. The
vmn-exp copies used to check .vmn/conf.yml only and any tracked file under the
app dir, so they re-initialized legacy repos and skipped half-set-up apps.
"""
import os
import subprocess

import pytest
from exp_helpers import _experiment, _init_app, _run_vmn_init, _stamp_app
from version_stamp.core.constants import INIT_COMMIT_MESSAGE

from vmn_exp.sdk import start_run

CUSTOM = "# kept by the user\nver.yml\n"


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)
    yield
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)


def _git(app_layout, *args):
    return subprocess.run(
        ["git", *args], cwd=app_layout.repo_path, check=True, capture_output=True, text=True
    ).stdout


def _init_commits(app_layout):
    return _git(app_layout, "log", "--format=%s").splitlines().count(INIT_COMMIT_MESSAGE)


def _gitignore(app_layout):
    with open(os.path.join(app_layout.repo_path, ".vmn", ".gitignore")) as f:
        return f.read()


def _legacy_repo(app_layout):
    """A stamped repo with a committed .vmn/.gitignore but no .vmn/conf.yml."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    _git(app_layout, "rm", "-q", ".vmn/conf.yml")
    _git(app_layout, "commit", "-q", "-m", "legacy layout")
    with open(os.path.join(app_layout.repo_path, ".vmn", ".gitignore"), "a") as f:
        f.write(CUSTOM)
    _git(app_layout, "commit", "-q", "-am", "custom ignore")
    _git(app_layout, "push", "-q")


def _app_with_only_conf_committed(app_layout, name):
    _run_vmn_init()
    conf_path = os.path.join(app_layout.repo_path, ".vmn", name, "conf.yml")
    os.makedirs(os.path.dirname(conf_path))
    app_layout.write_conf(conf_path, default_release_mode="patch")


def _ver_file_tracked(app_layout, name):
    tracked = _git(app_layout, "ls-files", f".vmn/{name}")
    return f".vmn/{name}/last_known_app_version.yml" in tracked.splitlines()


def test_exp_create_does_not_reinit_a_repo_with_only_gitignore(app_layout):
    _legacy_repo(app_layout)
    inits = _init_commits(app_layout)

    assert _experiment("new_app", note="n", extra_args=["--new-app"]) == 0

    assert _init_commits(app_layout) == inits
    assert CUSTOM in _gitignore(app_layout)


def test_exp_create_inits_an_app_with_only_conf_committed(app_layout):
    _app_with_only_conf_committed(app_layout, "new_app")

    assert _experiment("new_app", note="n") == 0

    assert _ver_file_tracked(app_layout, "new_app")


def test_start_run_does_not_reinit_a_repo_with_only_gitignore(app_layout):
    _legacy_repo(app_layout)
    inits = _init_commits(app_layout)

    with start_run("new_app") as run:
        assert run.id

    assert _init_commits(app_layout) == inits
    assert CUSTOM in _gitignore(app_layout)


def test_start_run_inits_an_app_with_only_conf_committed(app_layout):
    _app_with_only_conf_committed(app_layout, "new_app")

    with start_run("new_app") as run:
        assert run.id.startswith("0.0.0-dev.")

    assert _ver_file_tracked(app_layout, "new_app")
