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


def _reports(tmp_path):
    return sorted(p.name for p in tmp_path.glob("report_*.html"))


def test_pass_serial_runs_only_the_serial_pass(tmp_path):
    result = _run(tmp_path, "--pass", "serial")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("= 1 passed") == 1, result.stdout
    assert "-m serial" in result.stdout
    assert "not serial and not emulator" not in result.stdout
    assert _reports(tmp_path) == ["report_core_all_serial.html"]


def test_pass_parallel_runs_only_the_parallel_pass(tmp_path):
    result = _run(tmp_path, "--pass", "parallel")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("= 1 passed") == 1, result.stdout
    assert "not serial and not emulator" in result.stdout
    assert "-m serial" not in result.stdout
    assert _reports(tmp_path) == ["report_core_all.html"]


def test_pass_both_is_the_default(tmp_path):
    result = _run(tmp_path, "--pass", "both")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _reports(tmp_path) == ["report_core_all.html", "report_core_all_serial.html"]


def test_an_unknown_pass_is_refused(tmp_path):
    result = _run(tmp_path, "--pass", "nightly")
    assert result.returncode == 1
    assert "Usage" in result.stdout


def test_a_pass_left_empty_by_the_filter_fails_when_it_runs_alone(tmp_path):
    result = _run(tmp_path, "--pass", "parallel", "--specific_test", "test_runs_alone")
    assert result.returncode == 5, result.stdout + result.stderr


def test_a_very_long_specific_test_still_writes_its_report(tmp_path):
    expr = " or ".join(["test_runs_alone"] + [f"test_not_here_{i}" for i in range(120)])
    assert len(expr) > 2000
    result = _run(tmp_path, "--pass", "serial", "--specific_test", expr)
    assert result.returncode == 0, result.stdout + result.stderr
    (report,) = _reports(tmp_path)
    assert len(report.encode()) <= 255
    assert report.endswith("_serial.html")
