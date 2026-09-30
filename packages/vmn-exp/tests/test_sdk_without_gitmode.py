"""vmn-exp-sdk alone (no vmn_exp.gitmode installed): git-free runs work, and a
run that needs git fails with a pointer to the full package."""
import os
import subprocess
import sys

from exp_helpers import _SRC_PATH, _PY

_BLOCK_GITMODE = """
import sys
sys.modules["vmn_exp.gitmode"] = None  # as if vmn-exp were not installed
"""


def _run(code, cwd, env=None):
    return subprocess.run(
        [_PY, "-c", _BLOCK_GITMODE + code], cwd=cwd, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": _SRC_PATH, **(env or {})},
    )


def test_a_checkout_run_without_gitmode_says_to_install_vmn_exp(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    proc = _run(
        "from vmn_exp.sdk import start_run\nstart_run('app')\n", str(tmp_path)
    )
    assert proc.returncode != 0
    assert "pip install vmn-exp" in proc.stderr, proc.stderr


def test_a_git_free_run_without_gitmode_records_metrics(tmp_path):
    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text(
        "app_name: app\nverstr: 0.0.1-dev.abc1234.def5678\nbase_version: 0.0.1\n"
        "changesets: {}\n"
    )
    store = tmp_path / "store"
    proc = _run(
        "from vmn_exp.sdk import start_run\n"
        "with start_run('app') as run:\n"
        "    run.log_metric('loss', 0.5)\n"
        "print(run.id)\n",
        str(tmp_path),
        env={"VMN_SNAPSHOT_METADATA": str(meta), "VMN_EXPERIMENT_DIR": str(store)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "vmn_exp.gitmode" not in proc.stderr
    assert proc.stdout.strip()
