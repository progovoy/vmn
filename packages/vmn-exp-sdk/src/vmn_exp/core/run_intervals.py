"""A run's heartbeat and remote-sync cadences, settable from an image.

Precedence: explicit (``start_run`` kwarg, ``vmn-exp run --heartbeat-interval``
/ ``--sync-interval``) > ``VMN_EXP_HEARTBEAT_SEC`` / ``VMN_EXP_SYNC_SEC`` >
conf ``experiment.heartbeat_interval_sec`` / ``experiment.sync_interval_sec``
> 30 seconds. An env or conf value that is not a positive, finite number is
skipped, like ``VMN_EXP_MIN_STALE_SEC``.
"""
import math

from vmn_exp.core.status import DEFAULT_HEARTBEAT_INTERVAL_SEC, positive_env_sec

HEARTBEAT_ENV = "VMN_EXP_HEARTBEAT_SEC"
SYNC_ENV = "VMN_EXP_SYNC_SEC"
DEFAULT_SYNC_INTERVAL_SEC = 30


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(value) and value > 0):
        return None
    return int(value) if value.is_integer() else value


def _resolve(env, conf_key, default, exp_conf):
    conf = _positive((exp_conf or {}).get(conf_key))
    return _positive(positive_env_sec(env, conf or default))


def resolve_heartbeat_sec(explicit, exp_conf=None):
    """Seconds between heartbeats; a falsy *explicit* (None, 0) falls through."""
    if explicit:
        return explicit
    return _resolve(HEARTBEAT_ENV, "heartbeat_interval_sec",
                    DEFAULT_HEARTBEAT_INTERVAL_SEC, exp_conf)


def resolve_sync_sec(explicit, exp_conf=None):
    """Seconds between remote log syncs; an explicit 0 still means finish-only."""
    if explicit is not None:
        return explicit
    return _resolve(SYNC_ENV, "sync_interval_sec", DEFAULT_SYNC_INTERVAL_SEC, exp_conf)
