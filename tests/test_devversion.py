"""Tests for the version_stamp.devversion package.

A fast unit test (no Docker needed):
  test_devversion_imports_no_experiment_modules — subprocess guard: importing
      the four devversion modules loads no experiment/snapshot/ui code.
"""
import subprocess
import sys


def test_devversion_imports_no_experiment_modules():
    """Importing devversion sub-modules must not pull in any experiments code."""
    script = """
import sys

import version_stamp.devversion
import version_stamp.devversion.capture
import version_stamp.devversion.untracked
import version_stamp.devversion.apply
import version_stamp.devversion.materialize

FORBIDDEN_PREFIXES = (
    "vmn_exp.sdk",
    "vmn_exp.ui",
    "vmn_exp.snapshot",
    "version_stamp.core.experiment_",
    "vmn_exp.core.jsonl_tail",
    "vmn_exp.core.background",
    "vmn_exp.core.best_effort",
    "vmn_exp.core.record_files",
)

bad = [
    m for m in sys.modules
    if any(m == p or m.startswith(p + ".") or m.startswith(p)
           for p in FORBIDDEN_PREFIXES)
]
if bad:
    print("FAIL: experiment modules loaded:", sorted(bad))
    sys.exit(1)
sys.exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Experiment modules leaked into devversion import:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
