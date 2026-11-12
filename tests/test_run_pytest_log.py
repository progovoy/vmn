"""run_pytest.sh tees each run to a log named for its checkout and suite, so
two checkouts (agent worktrees) or two suites of one checkout running at once
never write into one shared log."""
import os
import pathlib
import shutil
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parent / "run_pytest.sh"

SAMPLE = '''
def test_{name}():
    pass
'''


def _checkout(root, name):
    """A copy of the script in a checkout of its own, with one test named *name*."""
    tests = root / name / "tests"
    tests.mkdir(parents=True)
    shutil.copy(SCRIPT, tests / "run_pytest.sh")
    (tests / f"test_{name}.py").write_text(SAMPLE.format(name=name))
    return tests


def _run(tests, log_dir, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHON"] = sys.executable
    result = subprocess.run(
        [str(tests / "run_pytest.sh"), "--module_name", str(tests), "--base_log_dir",
         str(log_dir), *args],
        cwd=tests, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _logs(log_dir):
    return {p.name: p.read_text() for p in log_dir.iterdir() if p.suffix == ".log"}


def test_two_checkouts_write_their_own_logs(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _run(_checkout(tmp_path, "one"), log_dir)
    _run(_checkout(tmp_path, "two"), log_dir)

    logs = _logs(log_dir)
    assert len(logs) == 2, sorted(logs)
    assert sorted(("one.py" in text, "two.py" in text) for text in logs.values()) == [
        (False, True), (True, False)]


def test_two_suites_of_one_checkout_write_their_own_logs(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    tests = _checkout(tmp_path, "one")
    _run(tests, log_dir, "--suite", "core")
    _run(tests, log_dir, "--suite", "exp")

    logs = _logs(log_dir)
    assert len(logs) == 2, sorted(logs)
    assert sorted(name for name in logs if "core" in name) != []
    assert sorted(name for name in logs if "exp" in name) != []


def test_the_run_says_where_its_log_is(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    tests = _checkout(tmp_path, "one")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHON"] = sys.executable
    result = subprocess.run(
        [str(tests / "run_pytest.sh"), "--module_name", str(tests), "--base_log_dir",
         str(log_dir)],
        cwd=tests, env=env, capture_output=True, text=True,
    )

    (log,) = _logs(log_dir)
    assert f"Log: {log_dir / log}" in result.stdout
