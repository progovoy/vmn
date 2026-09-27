"""CLI plugin registry — CommandSpec, registry helpers, dev-version loader hook.

Boundary rules (see PLAN.md §2.2):
  - This module is STAMPING; it must not import any experiments module.
  - Experiment-side plugins register themselves here; stamping code dispatches
    through the registry without needing to know about experiment modules.

Usage:
    from version_stamp.cli.plugin_api import CommandSpec, register, find

    # In a plugin module (experiments side):
    register(CommandSpec(names=("exp", "experiment"), add_parser=..., handle=...))

    # In stamping code (entry.py, args.py):
    spec = find(args.command)  # None if not a plugin command
    if spec is not None:
        return spec.handle(ctx)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, FrozenSet, Optional, Tuple


@dataclass
class CommandSpec:
    """Specification for a plugin-managed CLI command.

    Attributes
    ----------
    names:
        Primary name and aliases, e.g. ``("experiment", "exp")``.
    add_parser:
        Callable ``add_parser(subparsers) -> argparse.ArgumentParser`` that
        registers the command's subparser.  Called once during arg-parse setup.
    handle:
        Callable ``handle(ctx) -> int`` where *ctx* is a ``VMNContainer``.
        Returns 0 on success, non-zero on error.
    access:
        ``"local"`` or ``"remote"``; mirrors the ``VMN_ARGS`` values.
    read_only_actions:
        Set of action names (``args.action``) that skip the repo lock.
    split_after_double_dash:
        When True, ``parse_user_commands`` splits ``--`` for this command and
        attaches the tail as ``args.run_cmd``.
    run_without_repo:
        Optional callable ``run_without_repo(args) -> Optional[int]``.  If it
        returns a non-None value, the call is handled without resolving a git
        repo and acquiring the lock.  Return ``None`` to fall through to normal
        repo-aware dispatch.
    """

    names: Tuple[str, ...]
    add_parser: Callable
    handle: Callable
    access: str = "local"
    read_only_actions: FrozenSet[str] = field(default_factory=frozenset)
    split_after_double_dash: bool = False
    run_without_repo: Optional[Callable] = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: list = []


def register(spec: CommandSpec) -> None:
    """Add *spec* to the registry.  Call from a plugin's module-level code."""
    _registry.append(spec)


def specs() -> list:
    """Return a snapshot of all registered specs in registration order."""
    return list(_registry)


def find(name: str) -> Optional[CommandSpec]:
    """Return the first registered spec whose ``names`` tuple includes *name*."""
    for spec in _registry:
        if name in spec.names:
            return spec
    return None


# ---------------------------------------------------------------------------
# Dev-version loader hook
# ---------------------------------------------------------------------------

_dev_version_loader: Optional[Callable] = None


def register_dev_version_loader(fn: Callable) -> None:
    """Register *fn* as the handler for ``vmn goto <dev-verstr>`` / show --dev.

    ``fn(vcs, params, version) -> int``.  The snapshot/experiment plugin
    registers itself here so that ``output.py`` and ``commands.py`` can
    restore dev-version state without importing experiments modules directly.
    """
    global _dev_version_loader
    _dev_version_loader = fn


def load_dev_version(vcs, params: dict, version: str) -> int:
    """Restore the repo to the state captured in a dev-version snapshot.

    Delegates to the registered loader.  Returns 1 and logs an error if no
    loader has been registered (snapshot plugin not loaded).
    """
    if _dev_version_loader is None:
        import logging as _logging

        _logging.getLogger(__name__).error(
            "Cannot restore dev version %s: snapshot plugin not loaded.", version
        )
        return 1
    return _dev_version_loader(vcs, params, version)
