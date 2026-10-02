"""The vmn-exp suite. It needs all three distributions (see docs/packaging.md)
and reuses the core suite's fixtures and helpers from the repo's tests/ dir.
"""
import pathlib
import sys

# Import the tree under test (a worktree's, say), not whatever the venv has
# installed editable. Mirrors exp_helpers.SRC_DIRS for subprocesses.
_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "tests"))
for _dist in ("vmn-exp", "vmn-exp-sdk", "vmn"):
    sys.path.insert(0, str(_REPO / "packages" / _dist / "src"))

import pytest  # noqa: E402

from vmn_fixtures import (  # noqa: E402,F401  (fixtures and hooks pytest collects)
    app_layout,
    pytest_generate_tests,
    session_uuid,
    vmn_env_guard,
)
from pg_fixture import pg_dsn, pg_server_dsn  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _reset_experiment_writer_id():
    """The other half of vmn_env_guard's leak: a cached writer id outlives its
    env var (``VMN_WRITER_ID``, which vmn_env_guard restores)."""
    from vmn_exp.core import writer as experiment_writer

    yield

    experiment_writer._WRITER_ID = None


@pytest.fixture(autouse=True)
def _vmn_exp_commands_registered():
    """In-process tests parse `ui`/`exp`/`model` with vmn's parser, as `vmn-exp`
    does; register vmn-exp's commands the way its entry point would. (`vmn`
    itself refusing them is checked in a subprocess, in the core suite's
    test_vmn_refuses_exp_commands.py.)"""
    from vmn_exp.cli.plugin import register_all

    register_all()
