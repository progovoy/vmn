"""Load built-in plugin modules via importlib (string-based, not import edges).

``version_stamp.cli.plugins`` is EXEMPT from the stamping/experiments boundary
check (see tests/test_architecture_boundary.py EXEMPT_MODULES).  The module
names in ``BUILTIN_PLUGINS`` are plain strings so an AST-level boundary scan
never sees an import edge from stamping to experiments.

A missing plugin is tolerated with a debug log so that a stamping-only install
(where the experiments component is absent) keeps working.
"""
import importlib
import logging

_log = logging.getLogger(__name__)

BUILTIN_PLUGINS: tuple = ("vmn_exp.cli.plugin",)


def load_builtin_plugins() -> None:
    """Import every module listed in ``BUILTIN_PLUGINS`` and (re-)register specs.

    Calling this more than once is safe: each plugin's ``_register_all``
    function is idempotent and skips specs that are already in the registry.
    This allows specs to be restored after a test resets the registry.
    """
    for module_name in BUILTIN_PLUGINS:
        try:
            mod = importlib.import_module(module_name)
            # Call _register_all if available so specs survive a registry reset
            if hasattr(mod, "_register_all"):
                mod._register_all()
        except ImportError:
            _log.debug("Plugin %s not available; stamping continues without it", module_name)
