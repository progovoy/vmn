"""The core vmn suite. It runs with vmn's source root only and with ``vmn_exp``
made unimportable, so it passes without vmn-exp installed. The vmn-exp suite
lives in packages/vmn-exp/tests (see its conftest.py).
"""
import pathlib
import sys

# Import the tree under test (a worktree's, say), not whatever the venv has
# installed editable. Mirrors helpers.SRC_DIRS for subprocesses.
_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "packages" / "vmn" / "src"))

import no_vmn_exp  # noqa: E402

no_vmn_exp.block()

from vmn_fixtures import (  # noqa: E402,F401  (fixtures and hooks pytest collects)
    app_layout,
    pytest_generate_tests,
    session_uuid,
    vmn_env_guard,
)
