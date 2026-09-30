"""The `vmn-exp` command owns experiments, models and the UI; `vmn` does not."""
import os
import subprocess

from exp_helpers import _SRC_PATH, _PY, _bootstrap


def _vmn_exp(app_layout, *argv):
    env = {**os.environ, "VMN_WORKING_DIR": app_layout.repo_path,
           "PYTHONPATH": _SRC_PATH}
    env.pop("VMN_EXPERIMENT_ID", None)
    return subprocess.run(
        [_PY, "-m", "vmn_exp.cli", *argv], cwd=app_layout.repo_path, env=env,
        capture_output=True, text=True,
    )


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


def test_vmn_exp_points_snapshot_at_vmn(app_layout):
    _bootstrap(app_layout)
    proc = _vmn_exp(app_layout, "snapshot", app_layout.app_name)
    assert proc.returncode == 2, proc.stderr
    assert "vmn snapshot" in proc.stderr


