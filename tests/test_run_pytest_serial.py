"""run_pytest.sh runs ``serial``-marked tests (timing benchmarks) in their own
one-process pass after the parallel one, so 29 busy workers never skew them."""
import os
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parent / "run_pytest.sh"

SAMPLE = '''
import os
import pytest


def test_runs_on_a_worker():
    assert "PYTEST_XDIST_WORKER" in os.environ


@pytest.mark.serial
def test_runs_alone():
    assert "PYTEST_XDIST_WORKER" not in os.environ
'''


def _run(tmp_path, *args):
    (tmp_path / "test_sample.py").write_text(SAMPLE)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHON"] = sys.executable
    return subprocess.run(
        [str(SCRIPT), "--module_name", str(tmp_path), "--base_log_dir", str(tmp_path), *args],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )


def test_serial_tests_run_in_their_own_pass_without_workers(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("= 1 passed") == 2, result.stdout  # one per pass


def test_a_filter_that_leaves_one_pass_empty_still_succeeds(tmp_path):
    result = _run(tmp_path, "--specific_test", "test_runs_alone")
    assert result.returncode == 0, result.stdout + result.stderr
