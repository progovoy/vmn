"""What a user gets from `pip install "vmn[exp,ui]"`, verified against a wheel.

Every other test imports version_stamp from the checkout, so a packaging
mistake — a subpackage missing from setup.py, the dashboard's static assets
left out of package_data, an extra whose name drifted from the docs — is
invisible to them and only shows up after a release. These build a real wheel
and install it into a throwaway venv with an empty PYTHONPATH, so nothing can
be satisfied by the source tree.

The venv install needs the package index. If it is unreachable the tests skip
rather than fail; anything else that goes wrong is a real packaging defect.
"""
import os
import subprocess
import zipfile

import pytest
from helpers import _PROJECT_ROOT, _PY

# Built once per session: ~10s for the wheel, ~30s for the venv, and every test
# here reads the same artifact.
_TIMEOUT = 900


def _pip(*args, python=_PY):
    return subprocess.run(
        [python, "-m", "pip", *args],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )


@pytest.fixture(scope="session")
def wheel_path(tmp_path_factory):
    """Build vmn's wheel exactly as `make _build` would."""
    out = tmp_path_factory.mktemp("wheelhouse")
    proc = _pip("wheel", "--no-deps", "--no-build-isolation", "-w", str(out), _PROJECT_ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    wheels = list(out.glob("vmn-*.whl"))
    assert len(wheels) == 1, f"expected one vmn wheel, got {wheels}"
    return wheels[0]


@pytest.fixture(scope="session")
def installed_venv(tmp_path_factory, wheel_path):
    """A clean venv with `vmn[exp,ui]` installed from the wheel.

    Returns the venv's (python, vmn) executables.
    """
    venv_dir = tmp_path_factory.mktemp("vmn_install")
    proc = subprocess.run(
        [_PY, "-m", "venv", str(venv_dir)],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python = str(bin_dir / ("python.exe" if os.name == "nt" else "python"))

    proc = _pip("install", f"{wheel_path}[exp,ui]", python=python)
    if proc.returncode != 0:
        blob = proc.stdout + proc.stderr
        if "Temporary failure in name resolution" in blob or "Network is" in blob:
            pytest.skip("no package index reachable")
        pytest.fail(blob)

    return python, str(bin_dir / ("vmn.exe" if os.name == "nt" else "vmn"))


def _in_venv(python, code, cwd):
    """Run code in the installed venv with the checkout kept off sys.path."""
    env = dict(os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1")
    return subprocess.run(
        [python, "-c", code],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=_TIMEOUT,
    )


def test_the_wheel_ships_every_subpackage(wheel_path):
    """A package missing from setup.py imports fine in-tree and not once installed."""
    with zipfile.ZipFile(wheel_path) as zf:
        names = set(zf.namelist())

    for package in ("version_stamp/exp", "version_stamp/ui", "version_stamp/ui/readers"):
        assert f"{package}/__init__.py" in names, f"{package} is not in the wheel"


def test_the_wheel_ships_the_dashboard_assets(wheel_path):
    """`vmn ui` serves prebuilt static files; package_data has to carry them."""
    with zipfile.ZipFile(wheel_path) as zf:
        static = [n for n in zf.namelist() if "/ui/static/" in n]

    assert any(n.endswith("index.html") for n in static), static
    assert any("/assets/" in n for n in static), static


def test_the_installed_cli_runs(installed_venv, tmp_path):
    python, vmn = installed_venv
    proc = subprocess.run(
        [vmn, "--version"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=dict(os.environ, PYTHONPATH=""),
        timeout=_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip(), "vmn --version printed nothing"


def test_the_exp_sdk_imports_from_the_installed_package(installed_venv, tmp_path):
    """`pip install vmn[exp]` has to give a working `from version_stamp.exp import ...`."""
    python, _ = installed_venv
    proc = _in_venv(
        python,
        "import version_stamp.exp as exp, version_stamp.exp.reader as reader\n"
        "assert exp.start_run and exp.autolog and reader.list_runs\n"
        "print(exp.__file__)\n",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Not the checkout: an import satisfied by the source tree proves nothing.
    assert _PROJECT_ROOT not in proc.stdout


def test_the_ui_extra_installs_its_dependencies(installed_venv, tmp_path):
    """The ui extra exists so importing the app does not need a second pip install."""
    python, _ = installed_venv
    proc = _in_venv(
        python,
        "import fastapi, uvicorn\n"
        "from version_stamp.ui.server import create_app\n"
        "assert create_app\n"
        "print('ok')\n",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok" in proc.stdout


def test_the_exp_extra_does_not_drag_in_a_framework(installed_venv, tmp_path):
    """[exp] must stay small — autolog patches whatever the user already has."""
    python, _ = installed_venv
    proc = _in_venv(
        python,
        "import importlib.util as u;"
        "print([m for m in ('torch', 'tensorflow', 'sklearn', 'xgboost')"
        " if u.find_spec(m)])",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "[]", f"[exp] pulled in {proc.stdout.strip()}"
