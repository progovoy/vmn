"""Load the plugins installed packages declare under the ``vmn.plugins`` entry
point group (vmn-exp registers its dev-version loader there). vmn names no plugin itself.

A plugin that fails to import is tolerated with a debug log so that a broken or
partial install keeps stamping working.
"""
import logging
from importlib.metadata import entry_points

_log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "vmn.plugins"


def _plugin_entry_points():
    found = entry_points()
    if hasattr(found, "select"):
        group = found.select(group=ENTRY_POINT_GROUP)
    else:
        group = found.get(ENTRY_POINT_GROUP, [])  # Python < 3.10
    # An editable install can expose the same distribution's metadata twice.
    return list({(ep.name, ep.value): ep for ep in group}.values())


def load_builtin_plugins() -> None:
    """Call every installed plugin's register hook.

    Hooks must be idempotent: this runs on every command, and again after a
    test resets the registry.
    """
    for entry_point in _plugin_entry_points():
        try:
            entry_point.load()()
        except ImportError:
            _log.debug("Plugin %s not available; stamping continues without it",
                       entry_point.name)
