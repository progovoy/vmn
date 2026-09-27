"""Tests for the two-distribution packaging: default ``vmn`` wheel and slim
``vmn-exp`` wheel (built with ``VMN_DIST=exp``).

The unit tests exec setup.py in-process (stubbing out setuptools.setup so it
does not actually run) to call the package-selection helpers directly.
The smoke test builds a real wheel and installs it into a throwaway venv.
"""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_PY = sys.executable or "python3"
_TIMEOUT = 900


# ---------------------------------------------------------------------------
# Helper: exec setup.py without triggering a real build
# ---------------------------------------------------------------------------

def _exec_setup_ns():
    """Execute setup.py in-process and return its global namespace.

    setuptools.setup is replaced with a no-op so we can inspect the helpers
    without actually running a build.  CWD is set to ROOT so that
    ``open("tests/requirements.txt")`` inside setup.py resolves correctly.
    """
    import setuptools as _st

    real_setup = _st.setup
    _st.setup = lambda **kw: None  # type: ignore[assignment]
    orig_dir = os.getcwd()
    ns: dict = {}
    try:
        os.chdir(ROOT)
        src = (ROOT / "setup.py").read_text()
        exec(compile(src, str(ROOT / "setup.py"), "exec"), ns)  # noqa: S102
    finally:
        _st.setup = real_setup
        os.chdir(orig_dir)
    return ns


# ---------------------------------------------------------------------------
# Unit tests — no subprocess, no build
# ---------------------------------------------------------------------------

def test_exp_dist_packages_subset():
    """vmn-exp packages are a strict subset of the default vmn packages."""
    ns = _exec_setup_ns()
    select = ns["_select_packages"]

    full = set(select("vmn"))
    slim = set(select("exp"))

    assert slim < full, "slim packages must be a proper subset of full packages"

    # Required slim contents
    for pkg in ("vmn_exp", "vmn_exp.sdk", "vmn_exp.core", "vmn_exp.storage",
                "vmn_exp.registry", "vmn_exp.snapshot"):
        assert pkg in slim, f"{pkg} must be in the slim (exp) distribution"

    # Minimal version_stamp slice included at import time:
    # - core: logging, utils, constants, repo_lock, models
    # - cli: coldstart.py imports INIT_FILENAME from cli.constants at module level
    # - devversion: snapshot.__init__ re-exports dev-version helpers
    for pkg in ("version_stamp", "version_stamp.core",
                "version_stamp.cli", "version_stamp.devversion"):
        assert pkg in slim, f"{pkg} must be in the slim (exp) distribution"

    # Heavy stamping packages must NOT be in the slim wheel
    for pkg in ("version_stamp.stamping", "version_stamp.backends",
                "version_stamp.compat"):
        assert pkg not in slim, f"{pkg} must not be in the slim distribution"


def test_exp_dist_requires_only_yaml_filelock():
    """The slim wheel's install_requires must be only PyYAML and filelock."""
    ns = _exec_setup_ns()
    select_req = ns["_select_requires"]

    slim_reqs = [r.lower() for r in select_req("exp")]

    # Must have PyYAML and filelock
    assert any(r.startswith("pyyaml") for r in slim_reqs), "PyYAML missing from slim requires"
    assert any(r.startswith("filelock") for r in slim_reqs), "filelock missing from slim requires"

    # Must NOT have heavy stamping dependencies
    heavy = ("gitpython", "argcomplete", "questionary", "rich", "jinja2",
             "tomlkit", "packaging")
    for h in heavy:
        assert not any(r.startswith(h) for r in slim_reqs), (
            f"'{h}' must not be in the slim wheel's install_requires"
        )

    # Only two entries: PyYAML and filelock
    assert len(slim_reqs) == 2, (
        f"Slim install_requires should have exactly 2 entries (PyYAML + filelock), "
        f"got {slim_reqs!r}"
    )


def test_default_dist_unchanged():
    """The default (vmn) packages and requirements are the full set."""
    import ast

    ns = _exec_setup_ns()
    select = ns["_select_packages"]
    select_req = ns["_select_requires"]

    # Packages: must equal all on-disk subpackages
    declared = set(select("vmn"))
    version_stamp_dir = ROOT / "version_stamp"
    vmn_exp_dir = ROOT / "vmn_exp"
    on_disk = set()
    for top in (version_stamp_dir, vmn_exp_dir):
        for dirpath, _dirs, filenames in os.walk(top):
            if "__init__.py" in filenames:
                rel = os.path.relpath(dirpath, ROOT)
                on_disk.add(rel.replace(os.sep, "."))

    missing = on_disk - declared
    stale = declared - on_disk
    assert not missing, f"Packages on disk but missing from default dist: {sorted(missing)}"
    assert not stale, f"Packages in default dist but not on disk: {sorted(stale)}"

    # Requirements: must match tests/requirements.txt
    req_lines = [
        ln.strip()
        for ln in (ROOT / "tests" / "requirements.txt").read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    default_reqs = select_req("vmn")
    assert set(default_reqs) == set(req_lines), (
        f"Default install_requires drifted from tests/requirements.txt.\n"
        f"  select_req('vmn') = {sorted(default_reqs)}\n"
        f"  requirements.txt  = {sorted(req_lines)}"
    )


# ---------------------------------------------------------------------------
# Slow install smoke test
# ---------------------------------------------------------------------------

def _run_pip(python, *args, extra_env=None):
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [python, "-m", "pip", *args],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        env=env,
    )


@pytest.fixture(scope="session")
def slim_wheel_path(tmp_path_factory):
    """Build the vmn-exp slim wheel (VMN_DIST=exp).

    Cleans the source-tree build/ and *.egg-info artifacts before building so
    a stale default-build directory does not bleed into the slim wheel.
    """
    import shutil

    out = tmp_path_factory.mktemp("slim_wheelhouse")

    # Remove stale build artefacts from the source tree so the two builds
    # (default vmn and slim vmn-exp) never share a build/lib directory.
    for stale in list(ROOT.glob("build")) + list(ROOT.glob("*.egg-info")):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)

    proc = subprocess.run(
        [_PY, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "-w", str(out), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        env=dict(os.environ, VMN_DIST="exp", PYTHONNOUSERSITE="1"),
    )
    if proc.returncode != 0:
        pytest.fail(f"slim wheel build failed:\n{proc.stdout}\n{proc.stderr}")

    # pip normalises "vmn-exp" → "vmn_exp" in the wheel filename
    wheels = list(out.glob("vmn_exp-*.whl"))
    assert len(wheels) == 1, f"expected exactly one slim wheel, got {wheels}"
    return wheels[0]


@pytest.fixture(scope="session")
def slim_venv(tmp_path_factory, slim_wheel_path):
    """A venv with the slim vmn-exp wheel installed (no GitPython)."""
    venv_dir = tmp_path_factory.mktemp("slim_venv")
    proc = subprocess.run(
        [_PY, "-m", "venv", str(venv_dir)],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python = str(bin_dir / ("python.exe" if os.name == "nt" else "python"))

    # Install the slim wheel
    proc = _run_pip(python, "install", str(slim_wheel_path))
    if proc.returncode != 0:
        blob = proc.stdout + proc.stderr
        if "Temporary failure in name resolution" in blob or "Network is" in blob:
            pytest.skip("no package index reachable")
        pytest.fail(f"slim wheel install failed:\n{blob}")

    # Verify GitPython is absent
    check = subprocess.run(
        [python, "-c", "import git"],
        capture_output=True, text=True, timeout=30,
        env=dict(os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1"),
    )
    assert check.returncode != 0, (
        "GitPython must NOT be installed in the slim venv — "
        "the slim wheel must not declare it as a dependency"
    )

    return python


@pytest.mark.slow
def test_exp_only_wheel_records_git_free(slim_venv, tmp_path):
    """Install the slim wheel, run a git-free start_run, read the metric back.

    Verifies that a recording environment (container image, CI worker) that
    has no git repo and no GitPython can still record experiments and read
    them via vmn_exp.sdk.reader.
    """
    python = slim_venv
    exp_dir = str(tmp_path / "experiments")
    os.makedirs(exp_dir, exist_ok=True)
    metadata_dir = str(tmp_path / "snapshot_meta")
    os.makedirs(metadata_dir, exist_ok=True)
    metadata_path = os.path.join(metadata_dir, "metadata.yml")

    # Write a minimal snapshot metadata file so git-free mode engages
    with open(metadata_path, "w") as f:
        f.write(
            "verstr: '0.0.0-norepo.abc1234'\n"
            "app_name: test_slim_app\n"
            "diff_hash: abc1234\n"
        )

    # Script: record a run with one metric in git-free mode
    record_script = tmp_path / "record.py"
    record_script.write_text(f"""
import os
os.environ['VMN_EXPERIMENT_DIR'] = {exp_dir!r}
os.environ['VMN_SNAPSHOT_METADATA'] = {metadata_path!r}

import vmn_exp.sdk as sdk
run = sdk.start_run(app_name='test_slim_app')
run.log_metric('accuracy', 0.95)
run.finish()
print(run.id)
""")
    env = dict(os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1")
    proc = subprocess.run(
        [python, str(record_script)],
        capture_output=True, text=True, timeout=_TIMEOUT,
        env=env, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, (
        f"git-free start_run failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    verstr = proc.stdout.strip().splitlines()[-1].strip()
    assert verstr, f"No verstr printed; stdout={proc.stdout!r}"

    # Script: read the metric back via the reader.
    # Use snapshot_mode_storage() with VMN_EXPERIMENT_DIR set so the reader
    # does not need to call resolve_root_path() (which requires a git repo).
    read_script = tmp_path / "read.py"
    read_script.write_text(f"""
import os
os.environ['VMN_EXPERIMENT_DIR'] = {exp_dir!r}

from vmn_exp.sdk.create import snapshot_mode_storage
from vmn_exp.sdk.reader import list_runs

storage = snapshot_mode_storage()
rows = list_runs('test_slim_app', storage=storage)
assert rows, "No runs found in storage"
row = rows[0]
acc = row.get('metrics', {{}}).get('accuracy')
assert acc is not None, f"accuracy not in metrics: {{row.get('metrics')}}"
assert abs(acc - 0.95) < 1e-9, f"unexpected accuracy value: {{acc}}"
print('ok')
""")
    proc2 = subprocess.run(
        [python, str(read_script)],
        capture_output=True, text=True, timeout=_TIMEOUT,
        env=env, cwd=str(tmp_path),
    )
    assert proc2.returncode == 0, (
        f"read-back failed:\nstdout={proc2.stdout}\nstderr={proc2.stderr}"
    )
    assert "ok" in proc2.stdout
