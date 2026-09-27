"""Tests for version_stamp._aliases meta-path finder.

Uses a temporary probe table entry to test the alias mechanism without
requiring any real module moves.  All tests inject a fake mapping
  version_stamp._alias_probe_old  ->  vmn_exp_probe
into the _moved tables and create a throwaway module under a tmp dir.
"""
import importlib
import sys
import textwrap
import subprocess
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers for building fake "new" modules in a temp location
# ---------------------------------------------------------------------------

def _make_probe_pkg(tmp_path: Path) -> Path:
    """Create vmn_exp_probe package on disk and return its directory."""
    pkg_dir = tmp_path / "vmn_exp_probe"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("value = 42\n")
    sub_dir = pkg_dir / "sub"
    sub_dir.mkdir()
    (sub_dir / "__init__.py").write_text("sub_value = 99\n")
    (sub_dir / "leaf.py").write_text("leaf_value = 7\n")
    return pkg_dir


def _probe_inject(monkeypatch, tmp_path: Path, table_module_name: str = "core"):
    """
    Create the probe package on disk, add tmp_path to sys.path, and inject
    the mapping into version_stamp._moved.<table_module_name> so that
    the alias finder resolves:
      version_stamp._alias_probe_old -> vmn_exp_probe
    Returns the tmp_path (already on sys.path via monkeypatch).
    """
    _make_probe_pkg(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    # ensure _aliases and _moved are loaded
    import version_stamp._aliases  # noqa: F401
    moved = importlib.import_module(f"version_stamp._moved.{table_module_name}")
    monkeypatch.setitem(moved.TABLE, "version_stamp._alias_probe_old", "vmn_exp_probe")
    return tmp_path


def _clean_probe(monkeypatch):
    """Remove probe modules from sys.modules so each test starts fresh."""
    for key in (
        "vmn_exp_probe",
        "vmn_exp_probe.sub",
        "vmn_exp_probe.sub.leaf",
        "version_stamp._alias_probe_old",
        "version_stamp._alias_probe_old.sub",
        "version_stamp._alias_probe_old.sub.leaf",
    ):
        monkeypatch.delitem(sys.modules, key, raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_old_path_is_same_module_object(monkeypatch, tmp_path):
    """Importing old name gives the exact same module object as the new name."""
    _probe_inject(monkeypatch, tmp_path)
    _clean_probe(monkeypatch)

    old = importlib.import_module("version_stamp._alias_probe_old")
    new = importlib.import_module("vmn_exp_probe")
    assert old is new


def test_new_first_then_old_same_object(monkeypatch, tmp_path):
    """If new module is already in sys.modules, old name returns the same object."""
    _probe_inject(monkeypatch, tmp_path)
    _clean_probe(monkeypatch)

    new = importlib.import_module("vmn_exp_probe")
    old = importlib.import_module("version_stamp._alias_probe_old")
    assert old is new


def test_parent_attribute_set(monkeypatch, tmp_path):
    """After importing old name, the parent package gains the attribute."""
    _probe_inject(monkeypatch, tmp_path)
    _clean_probe(monkeypatch)

    importlib.import_module("version_stamp._alias_probe_old")

    import version_stamp
    assert hasattr(version_stamp, "_alias_probe_old")
    assert version_stamp._alias_probe_old is sys.modules["vmn_exp_probe"]


def test_submodule_prefix_mapping(monkeypatch, tmp_path):
    """version_stamp._alias_probe_old.sub.leaf -> vmn_exp_probe.sub.leaf (same object)."""
    _probe_inject(monkeypatch, tmp_path)
    _clean_probe(monkeypatch)

    old_sub = importlib.import_module("version_stamp._alias_probe_old.sub")
    new_sub = importlib.import_module("vmn_exp_probe.sub")
    assert old_sub is new_sub

    old_leaf = importlib.import_module("version_stamp._alias_probe_old.sub.leaf")
    new_leaf = importlib.import_module("vmn_exp_probe.sub.leaf")
    assert old_leaf is new_leaf


def test_monkeypatch_via_old_path_hits_new(monkeypatch, tmp_path):
    """monkeypatch.setattr via old module path mutates the shared object."""
    _probe_inject(monkeypatch, tmp_path)
    _clean_probe(monkeypatch)

    old_mod = importlib.import_module("version_stamp._alias_probe_old")
    monkeypatch.setattr(old_mod, "value", 999)
    new_mod = importlib.import_module("vmn_exp_probe")
    assert new_mod.value == 999


def test_mock_patch_string_via_old_path(monkeypatch, tmp_path):
    """mock.patch('version_stamp._alias_probe_old.value') patches the real module."""
    _probe_inject(monkeypatch, tmp_path)
    _clean_probe(monkeypatch)

    # pre-import so sys.modules has both names bound to same object
    importlib.import_module("version_stamp._alias_probe_old")

    with mock.patch("version_stamp._alias_probe_old.value", 1234):
        new_mod = importlib.import_module("vmn_exp_probe")
        assert new_mod.value == 1234


def test_finder_installed_once_and_cheap(tmp_path):
    """After `import version_stamp`, vmn_exp is NOT in sys.modules (lazy finder)."""
    code = textwrap.dedent("""
        import sys
        import version_stamp
        vmn_exp_mods = [m for m in sys.modules if m == "vmn_exp" or m.startswith("vmn_exp.")]
        # _moved and _aliases should be loaded, but not the vmn_exp runtime
        if vmn_exp_mods:
            print("LOADED:" + ",".join(sorted(vmn_exp_mods)))
            sys.exit(1)
    """)
    root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(root),
    )
    assert result.returncode == 0, (
        f"vmn_exp modules loaded eagerly: {result.stdout.strip()}\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_sys_modules_old_name_registered(monkeypatch, tmp_path):
    """sys.modules[old_name] must be set after importing via old path."""
    _probe_inject(monkeypatch, tmp_path)
    _clean_probe(monkeypatch)

    importlib.import_module("version_stamp._alias_probe_old")
    assert "version_stamp._alias_probe_old" in sys.modules
    assert sys.modules["version_stamp._alias_probe_old"] is sys.modules["vmn_exp_probe"]


def test_moved_tables_are_initially_empty():
    """All _moved table modules exist and have a TABLE dict that may be empty."""
    for area in ("storage", "core", "snapshot", "cli", "ui", "sdk"):
        mod = importlib.import_module(f"version_stamp._moved.{area}")
        assert isinstance(mod.TABLE, dict), f"version_stamp._moved.{area}.TABLE is not a dict"


def test_real_moved_storage_core_snapshot_aliases():
    """After h1/h2/h3 moves, old module names are the same object as new names."""
    pairs = [
        ("version_stamp.cli.snapshot", "vmn_exp.snapshot"),
        ("version_stamp.core.experiment_writer", "vmn_exp.core.writer"),
        ("version_stamp.cli.snapshot_storage_s3", "vmn_exp.storage.s3"),
    ]
    for old_name, new_name in pairs:
        old = importlib.import_module(old_name)
        new = importlib.import_module(new_name)
        assert old is new, f"{old_name!r} is not the same object as {new_name!r}"
        assert sys.modules[old_name] is sys.modules[new_name], (
            f"sys.modules[{old_name!r}] is not sys.modules[{new_name!r}]"
        )


def test_worker_command_imports_new_path():
    """The index worker subprocess command uses vmn_exp.core.index_workers, not the old path."""
    workers = importlib.import_module("vmn_exp.core.index_workers")
    cmd = workers._worker_command()
    cmd_str = " ".join(cmd)
    assert "vmn_exp.core.index_workers" in cmd_str, (
        f"worker command does not reference vmn_exp.core.index_workers: {cmd}"
    )
    assert "version_stamp.core.experiment_index_workers" not in cmd_str, (
        f"worker command still references old path version_stamp.core.experiment_index_workers: {cmd}"
    )
