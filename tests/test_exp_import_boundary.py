"""Tests that ``import version_stamp.exp`` does not pull in the CLI's heavy deps.

The SDK should be importable without dragging in git, rich, prompt_toolkit, jinja2,
tomlkit, questionary, argcomplete, version_stamp.backends, version_stamp.stamping,
version_stamp.cli.commands, or vmn_exp.ui.

P0.1 from the roadmap: lazy ``version_stamp/cli/__init__.py``.
"""
import os
import subprocess
import sys


# Subprocesses must import the version_stamp under test, not any editable
# install from a different checkout — mirror the pattern from tests/helpers.py.
_PY = sys.executable or "python3"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_HEAVY_MODULES = [
    "gitdb",
    "git",
    "rich",
    "questionary",
    "prompt_toolkit",
    "jinja2",
    "tomlkit",
    "argcomplete",
    "version_stamp.backends",
    "version_stamp.stamping",
    "version_stamp.cli.commands",
    "version_stamp.cli.config_tui",
    "version_stamp.cli.entry",
    "version_stamp.cli.args",
    "vmn_exp.ui",
]

_CHECK_SCRIPT = """\
import sys
import version_stamp.exp

loaded = []
for heavy in {heavy!r}:
    if any(k == heavy or k.startswith(heavy + '.') for k in sys.modules):
        loaded.append(heavy)

if loaded:
    print("HEAVY_LOADED:" + ",".join(loaded))
else:
    print("CLEAN")
"""


def test_sdk_import_skips_heavy_deps():
    """``import version_stamp.exp`` must not load CLI / git / rich / etc."""
    result = subprocess.run(
        [_PY, "-c", _CHECK_SCRIPT.format(heavy=_HEAVY_MODULES)],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
    )
    assert result.returncode == 0, (
        f"import check script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout.strip()
    assert output == "CLEAN", (
        f"Heavy modules were loaded when importing version_stamp.exp: "
        f"{output.removeprefix('HEAVY_LOADED:')}"
    )


def test_cli_main_still_importable():
    """The console entry point ``vmn = version_stamp.cli:main`` must still resolve."""
    script = """\
from version_stamp.cli import main, vmn_run
assert callable(main), "main is not callable"
assert callable(vmn_run), "vmn_run is not callable"
print("OK")
"""
    result = subprocess.run(
        [_PY, "-c", script],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
    )
    assert result.returncode == 0, (
        f"CLI import failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.strip() == "OK"
