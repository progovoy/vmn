"""Meta-path finder that aliases old module names to their new locations.

Populated by Phase-1 h-steps via version_stamp._moved.<area>.TABLE dicts.
Until those tables have entries, this finder is a no-op.

Guarantees:
  sys.modules[old_name] is sys.modules[new_name]  (same object)
  parent_pkg.<attr> is the new module object after import
  submodule paths are aliased via prefix substitution
  importing version_stamp never imports vmn_exp (lazy)
"""
import importlib
import importlib.abc
import importlib.machinery
import sys

_AREA_MODULES = ("storage", "core", "snapshot", "cli", "ui", "sdk")


def _resolve(fullname: str):
    """Return new_name for fullname, or None if not in any table.

    Only reads sys.modules for area modules (pre-imported by install() to
    prevent re-entrant find_spec calls and RecursionError).
    """
    for area in _AREA_MODULES:
        mod = sys.modules.get(f"version_stamp._moved.{area}")
        if mod is None:
            continue
        table = getattr(mod, "TABLE", {})
        for old_prefix, new_prefix in table.items():
            if fullname == old_prefix or fullname.startswith(old_prefix + "."):
                return new_prefix + fullname[len(old_prefix):]
    return None


def _set_parent_attr(old_name: str, module: object) -> None:
    """Set the attribute on the old parent package so attribute access works."""
    parts = old_name.rsplit(".", 1)
    if len(parts) == 2:
        parent_name, attr = parts
        parent = sys.modules.get(parent_name)
        if parent is not None:
            setattr(parent, attr, module)


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, new_name: str, old_name: str) -> None:
        self._new_name = new_name
        self._old_name = old_name

    def create_module(self, spec):  # type: ignore[override]
        # Import the canonical module.  Python then sets
        # sys.modules[old_name] = <return value>, giving identity equality.
        return importlib.import_module(self._new_name)

    def exec_module(self, module) -> None:  # type: ignore[override]
        # Module is already fully initialized (it is the new module).
        # Wire up the parent-package attribute.
        _set_parent_attr(self._old_name, module)


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):  # type: ignore[override]
        if not fullname.startswith("version_stamp."):
            return None
        new_name = _resolve(fullname)
        if new_name is None:
            return None
        return importlib.machinery.ModuleSpec(fullname, _AliasLoader(new_name, fullname))


_finder = _AliasFinder()


def install() -> None:
    """Install the alias finder into sys.meta_path (idempotent).

    Pre-imports all _moved area modules BEFORE inserting the finder so that
    _resolve() only reads sys.modules (never importlib.import_module),
    preventing RecursionError from re-entrant find_spec calls.

    Inserted at position 0 so it runs before PathFinder.  Without this, the
    aliased parent's __path__ would let PathFinder load the same file under
    the old name, creating a second module object.
    """
    if _finder in sys.meta_path:
        return
    # Pre-load area table modules while our finder is not yet active.
    for area in _AREA_MODULES:
        moved_name = f"version_stamp._moved.{area}"
        if moved_name not in sys.modules:
            try:
                importlib.import_module(moved_name)
            except ImportError:
                pass
    sys.meta_path.insert(0, _finder)
