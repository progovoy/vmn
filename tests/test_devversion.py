"""Tests for the version_stamp.devversion package.

Two fast unit tests (no Docker needed):
  test_snapshot_reexports_are_devversion_objects — snapshot.py re-exports the
      exact same callable objects as the devversion sub-modules.
  test_devversion_imports_no_experiment_modules — subprocess guard: importing
      the four devversion modules loads no experiment/snapshot/ui code.
"""
import subprocess
import sys

import pytest


def test_snapshot_reexports_are_devversion_objects():
    """snapshot.py re-exports from devversion must be the same objects."""
    import vmn_exp.snapshot as snap
    import version_stamp.devversion.apply as dv_apply
    import version_stamp.devversion.capture as dv_cap
    import version_stamp.devversion.materialize as dv_mat
    import version_stamp.devversion.untracked as dv_unt

    # capture
    assert snap.gather_create_data is dv_cap.gather_create_data
    assert snap._generate_patches is dv_cap._generate_patches
    assert snap._generate_dep_patches is dv_cap._generate_dep_patches
    assert snap._compute_diff_hash is dv_cap._compute_diff_hash
    assert snap._compute_verstr is dv_cap._compute_verstr
    assert snap._format_dev_verstr is dv_cap._format_dev_verstr
    assert snap._unique_snapshot_verstr is dv_cap._unique_snapshot_verstr

    # untracked
    assert snap.copy_untracked_files is dv_unt.copy_untracked_files
    assert snap._hash_untracked_content is dv_unt._hash_untracked_content

    # apply
    assert snap._apply_patches_to_workdir is dv_apply._apply_patches_to_workdir
    assert snap._apply_snapshot_patches is dv_apply._apply_snapshot_patches
    assert snap._reset_worktree is dv_apply._reset_worktree

    # materialize
    assert snap._materialize_workdir is dv_mat._materialize_workdir
    assert snap.get_git_difftool is dv_mat.get_git_difftool
    assert snap.render_tree_diff is dv_mat.render_tree_diff


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
    "version_stamp.exp",
    "version_stamp.ui",
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
