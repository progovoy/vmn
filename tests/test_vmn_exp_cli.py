"""The `vmn-exp` command owns experiments, models and the UI; `vmn` does not."""
import os
import subprocess


from helpers import _SRC_PATH, _PY, _bootstrap

from version_stamp.cli import vmn_run
from version_stamp.core.logging import reset_logger


def _vmn_exp(app_layout, *argv):
    env = {**os.environ, "VMN_WORKING_DIR": app_layout.repo_path,
           "PYTHONPATH": _SRC_PATH}
    env.pop("VMN_EXPERIMENT_ID", None)
    return subprocess.run(
        [_PY, "-m", "vmn_exp.cli", *argv], cwd=app_layout.repo_path, env=env,
        capture_output=True, text=True,
    )


def test_vmn_no_longer_knows_experiment_commands(app_layout):
    _bootstrap(app_layout)
    env = {**os.environ, "VMN_WORKING_DIR": app_layout.repo_path,
           "PYTHONPATH": _SRC_PATH}
    for command in ("exp", "experiment", "model", "ui"):
        proc = subprocess.run(
            [_PY, "-m", "version_stamp.cli.entry", command, "list", app_layout.app_name],
            cwd=app_layout.repo_path, env=env, capture_output=True, text=True,
        )
        assert proc.returncode == 2, (command, proc.stderr)
        assert "invalid choice" in proc.stderr


def test_vmn_exp_takes_experiment_actions_directly(app_layout):
    _bootstrap(app_layout)
    created = _vmn_exp(app_layout, "create", app_layout.app_name, "--note", "first")
    assert created.returncode == 0, created.stderr
    listed = _vmn_exp(app_layout, "list", app_layout.app_name)
    assert listed.returncode == 0, listed.stderr
    assert "first" in listed.stdout


def test_vmn_exp_still_accepts_a_leading_exp(app_layout):
    _bootstrap(app_layout)
    proc = _vmn_exp(app_layout, "exp", "list", app_layout.app_name)
    assert proc.returncode == 0, proc.stderr


def test_vmn_exp_owns_the_model_registry(app_layout):
    _bootstrap(app_layout)
    proc = _vmn_exp(app_layout, "model", "list", "--dir", app_layout.repo_path)
    assert proc.returncode == 0, proc.stderr


def test_vmn_exp_refuses_stamping_commands(app_layout):
    _bootstrap(app_layout)
    proc = _vmn_exp(app_layout, "stamp", "-r", "patch", app_layout.app_name)
    assert proc.returncode != 0
    assert "vmn stamp" in proc.stderr


def test_vmn_snapshot_works_through_the_installed_plugin(app_layout):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "f.txt", "x")
    with open(os.path.join(app_layout.repo_path, "f.txt"), "a") as f:
        f.write("dirty\n")
    reset_logger()
    assert vmn_run(["snapshot", app_layout.app_name])[0] == 0
