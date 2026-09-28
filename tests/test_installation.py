"""What users get from the three wheels (vmn, vmn-exp-sdk, vmn-exp).

Every other test imports from the checkout, so a packaging mistake — a missing
subpackage, the dashboard's assets left out, a file shipped by two wheels —
only shows up after a release. These build the real wheels and install them
into throwaway venvs with an empty PYTHONPATH.

The installs need the package index for third-party dependencies. If it is
unreachable the tests skip; anything else is a real packaging defect.
"""
import os
import subprocess
import zipfile

import pytest
from helpers import _PROJECT_ROOT, _PY

_TIMEOUT = 900
DISTS = ("vmn", "vmn-exp-sdk", "vmn-exp")


def _pip(*args, python=_PY):
    return subprocess.run(
        [python, "-m", "pip", *args], capture_output=True, text=True, timeout=_TIMEOUT
    )


@pytest.fixture(scope="session")
def wheelhouse(tmp_path_factory):
    """``{dist: wheel path}``, built as the release lane builds them.

    Built once for all xdist workers: concurrent builds of one source tree
    trip over each other's in-tree ``build/`` directories."""
    from filelock import FileLock

    shared = tmp_path_factory.getbasetemp().parent
    out = shared / "wheelhouse"
    with FileLock(str(shared / "wheelhouse.lock")):
        if not (out / "done").exists():
            out.mkdir(exist_ok=True)
            for dist in DISTS:
                source = os.path.join(_PROJECT_ROOT, "packages", dist)
                proc = _pip("wheel", "--no-deps", "--no-build-isolation", "-w", str(out),
                            source)
                assert proc.returncode == 0, proc.stdout + proc.stderr
            (out / "done").touch()
    wheels = {}
    for dist in DISTS:
        prefix = dist.replace("-", "_") + "-"
        [wheels[dist]] = [p for p in out.glob("*.whl") if p.name.startswith(prefix)]
    return wheels


def _names(wheel):
    with zipfile.ZipFile(wheel) as zf:
        return {n for n in zf.namelist() if ".dist-info/" not in n}


def _venv(tmp_path_factory, name, *requirements):
    """A clean venv with *requirements* installed. Pass the built wheels as
    paths: by name, pip would prefer a higher release from the index."""
    venv_dir = tmp_path_factory.mktemp(name)
    subprocess.run([_PY, "-m", "venv", str(venv_dir)], check=True, timeout=_TIMEOUT)
    python = str(venv_dir / "bin" / "python")
    proc = _pip("install", *requirements, python=python)
    if proc.returncode != 0:
        blob = proc.stdout + proc.stderr
        if "Temporary failure in name resolution" in blob or "Network is" in blob:
            pytest.skip("no package index reachable")
        pytest.fail(blob)
    return python


@pytest.fixture(scope="session")
def full_venv(tmp_path_factory, wheelhouse):
    return _venv(
        tmp_path_factory, "full", str(wheelhouse["vmn"]), str(wheelhouse["vmn-exp-sdk"]),
        f"{wheelhouse['vmn-exp']}[ui]",
    )


@pytest.fixture(scope="session")
def sdk_venv(tmp_path_factory, wheelhouse):
    return _venv(tmp_path_factory, "sdk_only", str(wheelhouse["vmn-exp-sdk"]))


def _in_venv(python, code, cwd):
    env = dict(os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1")
    return subprocess.run(
        [python, "-c", code], capture_output=True, text=True, cwd=cwd, env=env,
        timeout=_TIMEOUT,
    )


def test_no_file_ships_in_two_wheels(wheelhouse):
    seen = {}
    for dist, wheel in wheelhouse.items():
        for name in _names(wheel):
            assert name not in seen, f"{name} is in both {seen[name]} and {dist}"
            seen[name] = dist


def test_each_wheel_ships_its_own_subpackages(wheelhouse):
    vmn, sdk, full = (_names(wheelhouse[d]) for d in DISTS)
    assert "version_stamp/api.py" in vmn
    assert not any(n.startswith("vmn_exp/") for n in vmn)
    assert {"vmn_exp/sdk/__init__.py", "vmn_exp/storage/__init__.py",
            "vmn_exp/_base.py"} <= sdk
    assert not any(n.startswith(("version_stamp/", "vmn_exp/cli/", "vmn_exp/ui/"))
                   for n in sdk)
    assert {"vmn_exp/cli/main.py", "vmn_exp/gitmode/__init__.py",
            "vmn_exp/ui/readers/__init__.py"} <= full
    # PEP 420: a vmn_exp/__init__.py in either wheel would shadow the other.
    assert "vmn_exp/__init__.py" not in sdk | full


def test_vmn_exp_ships_the_dashboard_assets(wheelhouse):
    static = [n for n in _names(wheelhouse["vmn-exp"]) if "/ui/static/" in n]
    assert any(n.endswith("index.html") for n in static), static
    assert any("/assets/" in n for n in static), static


def test_the_installed_commands_run(full_venv, tmp_path):
    bin_dir = os.path.dirname(full_venv)
    env = dict(os.environ, PYTHONPATH="")
    for command in (["vmn", "--version"], ["vmn-exp", "--help"]):
        proc = subprocess.run(
            [os.path.join(bin_dir, command[0]), *command[1:]], capture_output=True,
            text=True, cwd=str(tmp_path), env=env, timeout=_TIMEOUT,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_vmn_gets_snapshot_from_the_installed_plugin(full_venv, tmp_path):
    proc = _in_venv(
        full_venv,
        "from version_stamp.cli.plugins import load_builtin_plugins\n"
        "from version_stamp.cli.plugin_api import find\n"
        "load_builtin_plugins()\n"
        "assert find('snapshot') is not None\n",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_ui_extra_installs_its_dependencies(full_venv, tmp_path):
    proc = _in_venv(
        full_venv, "import fastapi, uvicorn\nfrom vmn_exp.ui.server import create_app\n",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_sdk_alone_records_and_reads_a_git_free_run(sdk_venv, tmp_path):
    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text("verstr: '0.0.0-norepo.abc1234'\napp_name: slim\ndiff_hash: abc1234\n")
    store = str(tmp_path / "experiments")
    proc = _in_venv(
        sdk_venv,
        "import os, sys\n"
        f"os.environ['VMN_EXPERIMENT_DIR'] = {store!r}\n"
        f"os.environ['VMN_SNAPSHOT_METADATA'] = {str(meta)!r}\n"
        "from vmn_exp.sdk import start_run\n"
        "from vmn_exp.sdk.create import snapshot_mode_storage\n"
        "from vmn_exp.sdk.reader import list_runs\n"
        "with start_run('slim') as run:\n"
        "    run.log_metric('accuracy', 0.95)\n"
        "[row] = list_runs('slim', storage=snapshot_mode_storage())\n"
        "assert row['metrics']['accuracy'] == 0.95, row\n"
        "assert not any(m == 'git' or m.startswith('version_stamp') for m in sys.modules)\n",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_sdk_alone_has_neither_vmn_nor_the_platform(sdk_venv, tmp_path):
    proc = _in_venv(
        sdk_venv,
        "import importlib.util as u\n"
        "assert u.find_spec('version_stamp') is None\n"
        "assert u.find_spec('git') is None\n"
        "assert u.find_spec('vmn_exp.cli') is None\n",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
