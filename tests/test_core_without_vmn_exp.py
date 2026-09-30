"""The core suite runs without vmn-exp: its test infra and vmn itself work
when ``vmn_exp`` cannot be imported.

The dev venv has vmn-exp installed (editable), so "not installed" is simulated
in a subprocess: ``no_vmn_exp.block()`` makes every ``vmn_exp`` import raise
ModuleNotFoundError, exactly what a missing distribution does, whatever the
install kind (editable .pth, finder or regular site-packages). PYTHONPATH holds
only vmn's source root and the core tests dir.
"""
import os
import subprocess

from helpers import _PY, _SRC_PATH

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

_SCRIPT = """
import sys
import no_vmn_exp
no_vmn_exp.block()
try:
    import vmn_exp
except ImportError:
    pass
else:
    sys.exit("vmn_exp is importable")

import version_stamp
assert version_stamp.__file__.startswith(sys.argv[2]), version_stamp.__file__
import conftest, helpers, island_helpers, vmn_fixtures
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger

reset_logger()
assert vmn_run(["stamp", "-r", "patch", sys.argv[1]])[0] == 0
reset_logger()
assert vmn_run(["skill"])[0] == 0
loaded = [m for m in sys.modules if m.split(".")[0] == "vmn_exp"]
assert not loaded, loaded
"""


def test_core_infra_and_vmn_work_without_vmn_exp(app_layout):
    env = {
        **os.environ,
        "VMN_WORKING_DIR": app_layout.repo_path,
        "PYTHONPATH": os.pathsep.join([_SRC_PATH, _TESTS_DIR]),
    }
    proc = subprocess.run(
        [_PY, "-c", _SCRIPT, app_layout.app_name, _SRC_PATH],
        cwd=app_layout.repo_path, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
