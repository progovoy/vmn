"""start_run() and resume in a plain directory (no git) report that the
directory is not a checkout, before git mode is entered (plan 38 A3)."""
import os
import subprocess

from exp_helpers import _PY, _SRC_PATH

NOT_A_CHECKOUT = "not inside a git checkout"

_BLOCK_GITMODE = """
import sys
sys.modules["vmn_exp.gitmode"] = None  # as if vmn-exp were not installed
"""


def _run(code, cwd, env=None, prelude=""):
    base = {k: v for k, v in os.environ.items()
            if k not in ("VMN_WORKING_DIR", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                         "VMN_RESUME_RUN_ID", "VMN_EXPERIMENT_ID")}
    return subprocess.run(
        [_PY, "-c", prelude + code], cwd=cwd, capture_output=True, text=True,
        env={**base, "PYTHONPATH": _SRC_PATH, **(env or {})},
    )


def _plain_dir(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    return str(plain)


def _store_env(tmp_path):
    return {"VMN_APP_NAME": "app", "VMN_EXPERIMENT_DIR": str(tmp_path / "store")}


def test_start_run_in_a_plain_directory_raises_not_a_checkout_with_app_and_store_env_set(tmp_path):
    plain = _plain_dir(tmp_path)
    proc = _run("from vmn_exp.sdk import start_run\nstart_run()\n", plain,
                env=_store_env(tmp_path))
    assert proc.returncode != 0
    assert "RuntimeError" in proc.stderr, proc.stderr
    assert NOT_A_CHECKOUT in proc.stderr, proc.stderr
    assert plain in proc.stderr
    assert "VMN_LOGGER" not in proc.stderr


def test_start_run_in_a_plain_directory_without_app_name_reports_the_checkout_not_the_app(tmp_path):
    proc = _run("from vmn_exp.sdk import start_run\nstart_run()\n", _plain_dir(tmp_path))
    assert proc.returncode != 0
    assert NOT_A_CHECKOUT in proc.stderr, proc.stderr
    assert "Cannot infer the vmn app name" not in proc.stderr


def test_resume_run_id_in_a_plain_directory_raises_not_a_checkout(tmp_path):
    proc = _run("from vmn_exp.sdk import start_run\n"
                "start_run(run_id='0.0.1-dev.abc1234.def5678.r1')\n",
                _plain_dir(tmp_path), env=_store_env(tmp_path))
    assert proc.returncode != 0
    assert NOT_A_CHECKOUT in proc.stderr, proc.stderr
    assert "VMN_LOGGER" not in proc.stderr


def test_not_a_checkout_wins_over_git_mode_missing_on_an_sdk_only_path(tmp_path):
    proc = _run("from vmn_exp.sdk import start_run\nstart_run()\n", _plain_dir(tmp_path),
                env=_store_env(tmp_path), prelude=_BLOCK_GITMODE)
    assert proc.returncode != 0
    assert NOT_A_CHECKOUT in proc.stderr, proc.stderr
    assert "pip install vmn-exp" not in proc.stderr


def test_snapshot_metadata_mode_is_not_affected(tmp_path):
    plain = _plain_dir(tmp_path)
    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text(
        "app_name: app\nverstr: 0.0.1-dev.abc1234.def5678\nbase_version: 0.0.1\n"
        "changesets: {}\n"
    )
    proc = _run(
        "from vmn_exp.sdk import start_run\n"
        "with start_run('app') as run:\n"
        "    run.log_metric('loss', 0.5)\n"
        "print(run.id)\n",
        plain,
        env={"VMN_SNAPSHOT_METADATA": str(meta),
             "VMN_EXPERIMENT_DIR": str(tmp_path / "store")},
    )
    assert proc.returncode == 0, proc.stderr
    assert NOT_A_CHECKOUT not in proc.stderr
    assert proc.stdout.strip()
