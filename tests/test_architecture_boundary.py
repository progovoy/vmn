"""AST-based import-graph ratchet: stamping vs experiments boundary.

Run with --regen to regenerate architecture_known_violations.py:
    python tests/test_architecture_boundary.py --regen
"""
import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Classification data — kept as globs so later file-move steps only update here
# ---------------------------------------------------------------------------

# Globs for EXPERIMENTS modules (all under version_stamp/)
# Each entry: a module prefix.  Trailing "_" means "startswith(p)" match.
# No trailing "_" means exact-or-subpackage match (mod == p or mod.startswith(p + ".")).
# Special: "vmn_exp.snapshot" also matches "version_stamp.cli.snapshot_*".
EXPERIMENTS_GLOBS = (
    "version_stamp.exp",              # exp package and all submodules
    "version_stamp.ui",               # ui package and all submodules
    "vmn_exp.snapshot",     # cli/snapshot.py + cli/snapshot_storage*.py
    "version_stamp.cli.experiment",   # cli/experiment.py + cli/experiment_*.py
    "version_stamp.cli._builtin_exp_plugin",  # temporary plugin; moves to vmn_exp in step h4
    "version_stamp.core.experiment_", # core/experiment_*.py (trailing _ = prefix match)
    "vmn_exp.core.jsonl_tail",
    "vmn_exp.core.background",
    "vmn_exp.core.best_effort",
    "vmn_exp.core.record_files",
)

# Modules that are exempt from both sides of the boundary check
EXEMPT_MODULES = frozenset(
    {
        "version_stamp.cli.plugin_api",   # plugin registry — used by both sides
        "version_stamp.cli.plugins",      # plugin loader shim
    }
)

# Prefixes that are exempt (not yet present, reserved for future steps)
EXEMPT_PREFIXES = ()

# The ONE stamping module that experiments are allowed to import (future facade)
ALLOWED_FACADE = "version_stamp.api"

# Future vmn_exp package also counts as experiments if it exists
VMN_EXP_PACKAGE = "vmn_exp"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_VS_ROOT = _REPO_ROOT / "version_stamp"


def _is_exp(mod: str) -> bool:
    if mod == VMN_EXP_PACKAGE or mod.startswith(VMN_EXP_PACKAGE + "."):
        return True
    for p in EXPERIMENTS_GLOBS:
        if p.endswith("_"):
            if mod.startswith(p):
                return True
        else:
            if mod == p or mod.startswith(p + ".") or mod.startswith(p + "_"):
                return True
    return False


def _is_stamping(mod: str) -> bool:
    if not mod.startswith("version_stamp"):
        return False
    if _is_exp(mod):
        return False
    if mod in EXEMPT_MODULES:
        return False
    for ep in EXEMPT_PREFIXES:
        if mod.startswith(ep):
            return False
    return True


def _module_name(path: Path) -> str:
    rel = path.relative_to(_REPO_ROOT)
    return str(rel.with_suffix("")).replace(os.sep, ".")


def _collect_raw_imports(source: str, mod_name: str) -> list:
    """Return every module name referenced by import statements in *source*."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: list = []

    class _V(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                found.append(alias.name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module is None:
                self.generic_visit(node)
                return
            if node.level == 0:
                found.append(node.module)
            else:
                # Resolve relative import
                parts = mod_name.rsplit(".", node.level)
                base = parts[0] if len(parts) > 1 else ""
                if base:
                    target = f"{base}.{node.module}" if node.module else base
                    found.append(target)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            # importlib.import_module("literal")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.append(node.args[0].value)
            # __import__("literal")
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.append(node.args[0].value)
            self.generic_visit(node)

    _V().visit(tree)
    return found


def _scan_violations() -> frozenset:
    """Return frozenset of (importer, imported) violation pairs."""
    violations: set = set()

    for py_file in sorted(_VS_ROOT.rglob("*.py")):
        mod_name = _module_name(py_file)

        # Skip exempt modules
        if mod_name in EXEMPT_MODULES:
            continue
        if any(mod_name.startswith(ep) for ep in EXEMPT_PREFIXES):
            continue

        is_exp_mod = _is_exp(mod_name)
        is_stamp_mod = _is_stamping(mod_name)

        source = py_file.read_text()
        for imp in _collect_raw_imports(source, mod_name):
            if not (imp.startswith("version_stamp") or imp.startswith(VMN_EXP_PACKAGE)):
                continue
            # stamping → experiments (never allowed)
            if is_stamp_mod and _is_exp(imp):
                violations.add((mod_name, imp))
            # experiments → stamping (only ALLOWED_FACADE is ok)
            elif is_exp_mod and _is_stamping(imp) and imp != ALLOWED_FACADE:
                violations.add((mod_name, imp))

    # Also scan vmn_exp/ if it exists (future package)
    vmn_exp_root = _REPO_ROOT / "vmn_exp"
    if vmn_exp_root.exists():
        for py_file in sorted(vmn_exp_root.rglob("*.py")):
            mod_name = _module_name(py_file)
            source = py_file.read_text()
            for imp in _collect_raw_imports(source, mod_name):
                if imp.startswith("version_stamp") and _is_stamping(imp) and imp != ALLOWED_FACADE:
                    violations.add((mod_name, imp))

    return frozenset(violations)


def _all_vs_modules() -> frozenset:
    return frozenset(_module_name(p) for p in _VS_ROOT.rglob("*.py"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_new_boundary_violations() -> None:
    """Found violations must be a subset of the known allowlist."""
    from tests.architecture_known_violations import KNOWN_VIOLATIONS

    found = _scan_violations()
    new = found - KNOWN_VIOLATIONS
    if new:
        lines = "\n".join(f"  {a!r}  ->  {b!r}" for a, b in sorted(new))
        pytest.fail(
            f"{len(new)} new boundary violation(s) — add them to KNOWN_VIOLATIONS "
            f"only if they are intentional, otherwise fix the import:\n{lines}"
        )


def test_allowlist_has_no_stale_entries() -> None:
    """The allowlist must shrink as migration steps land, never grow stale."""
    from tests.architecture_known_violations import KNOWN_VIOLATIONS

    found = _scan_violations()
    stale = KNOWN_VIOLATIONS - found
    if stale:
        lines = "\n".join(f"  {a!r}  ->  {b!r}" for a, b in sorted(stale))
        pytest.fail(
            f"{len(stale)} stale entry/entries in KNOWN_VIOLATIONS — remove them "
            f"(run --regen to refresh the file):\n{lines}"
        )


def test_stamping_core_does_not_load_experiments() -> None:
    """Importing version_stamp.stamping + version_stamp.backends must not load any exp module."""
    code = textwrap.dedent(
        """
        import sys
        import version_stamp.stamping
        import version_stamp.backends
        exp_mods = [m for m in sys.modules if (
            m.startswith("version_stamp.exp")
            or m.startswith("version_stamp.ui")
            or m.startswith("vmn_exp.snapshot")
            or m.startswith("version_stamp.cli.experiment")
            or (m.startswith("version_stamp.core.experiment_"))
            or m in {
                "vmn_exp.core.jsonl_tail",
                "vmn_exp.core.background",
                "vmn_exp.core.best_effort",
                "vmn_exp.core.record_files",
            }
        )]
        if exp_mods:
            print("LOADED_EXP:" + ",".join(sorted(exp_mods)))
            sys.exit(1)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        loaded = result.stdout.strip()
        pytest.fail(
            f"Importing version_stamp.stamping/backends loaded experiment modules.\n"
            f"{loaded}\nstderr: {result.stderr[:500]}"
        )


def test_classification_covers_every_module() -> None:
    """Every .py file under version_stamp/ must be classified as stamping or experiments.

    New files that are neither stamping nor experiments (and not exempt) will fail here,
    forcing an explicit classification update in EXPERIMENTS_GLOBS.
    """
    unclassified = []
    for mod in sorted(_all_vs_modules()):
        if mod in EXEMPT_MODULES:
            continue
        if any(mod.startswith(ep) for ep in EXEMPT_PREFIXES):
            continue
        if not _is_stamping(mod) and not _is_exp(mod):
            unclassified.append(mod)
    if unclassified:
        lines = "\n".join(f"  {m}" for m in unclassified)
        pytest.fail(
            f"{len(unclassified)} module(s) not covered by EXPERIMENTS_GLOBS or stamping "
            f"(add them to EXPERIMENTS_GLOBS or an EXEMPT set):\n{lines}"
        )


# ---------------------------------------------------------------------------
# --regen helper (run as a script)
# ---------------------------------------------------------------------------

def _regen() -> None:
    violations = _scan_violations()
    stamp_to_exp = sum(1 for a, b in violations if _is_stamping(a))
    exp_to_stamp = sum(1 for a, b in violations if _is_exp(a))
    print(f"Found {len(violations)} violations "
          f"({stamp_to_exp} stamping→exp, {exp_to_stamp} exp→stamping)")

    lines = [
        "# AUTO-GENERATED by: python tests/test_architecture_boundary.py --regen",
        "# Shrinks as Phase 1 migration steps land. Never grows.",
        "KNOWN_VIOLATIONS: frozenset = frozenset(",
        "    {",
    ]
    for a, b in sorted(violations):
        lines.append(f'        ("{a}", "{b}"),')
    lines += ["    }", ")", ""]

    out_path = Path(__file__).parent / "architecture_known_violations.py"
    out_path.write_text("\n".join(lines))
    print(f"Written: {out_path}")


if __name__ == "__main__":
    if "--regen" in sys.argv:
        _regen()
    else:
        print("Usage: python tests/test_architecture_boundary.py --regen")
        sys.exit(1)
