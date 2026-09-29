"""The ``experiment:`` section of an app's conf: off the vcs that loaded it
(:func:`experiment_conf`), or read straight from ``.vmn/<app>/conf.yml`` by
callers that hold no vcs (:func:`read_experiment_conf` — the reader API, alerts
when no conf was handed over; the app conf only, no branch confs)."""
import logging
import os

from vmn_exp import _base

_LOGGER = logging.getLogger(__name__)


def experiment_conf(vcs):
    """The ``experiment:`` section of *vcs*'s conf.yml, ``{}`` without one."""
    return getattr(vcs, "experiment", None) or {}


def read_experiment_conf(app_name, root=None):
    """``conf.experiment`` of ``.vmn/<app>/conf.yml`` under *root* (default:
    the current checkout), or {}. Never raises."""
    if not app_name:
        return {}
    try:
        root = root or _base.resolve_root_path()
        path = os.path.join(root, ".vmn", *app_name.split("/"), "conf.yml")
        with open(path) as f:
            data = _base.yaml_safe_load(f.read()) or {}
        return (data.get("conf") or {}).get("experiment") or {}
    except Exception:
        _LOGGER.debug(f"No experiment conf for {app_name}", exc_info=True)
        return {}
