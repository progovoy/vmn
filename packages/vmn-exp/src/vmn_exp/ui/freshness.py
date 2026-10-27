#!/usr/bin/env python3
"""An app status's ``freshness`` (:mod:`vmn_exp.ui.routes_shell`): how old
the index the ui serves is and what its background refresh is doing, so the
dashboard can say it shows stale data.

``{as_of, refreshing, refresh_running_sec, phase, progress, refresh_failing,
last_error, stale_after_sec}`` from the index's own state
(:meth:`ExperimentIndex.freshness`: ``as_of`` survives restarts, ``phase``,
``progress``) and its refresher's health (:meth:`Refresher.health`). A
refresh running past :data:`STUCK_REFRESH_SEC` whose phase and progress have
not moved for as long (the index's ``stalled_sec``) counts as failing
(stuck), like a failure streak or a refresh thread that is gone. ``stale_after_sec``
is the age past which the dashboard warns (conf
``experiment.ui.stale_after_min`` of a checkout's app, else
:data:`DEFAULT_STALE_AFTER_MIN`).
"""
import datetime

from vmn_exp.ui.refresher import SLOW_REFRESH_SEC

STUCK_REFRESH_SEC = SLOW_REFRESH_SEC
DEFAULT_STALE_AFTER_MIN = 5


def freshness(health, state, stale_after_min=DEFAULT_STALE_AFTER_MIN):
    """The payload of a refresher's *health* and an index's *state*."""
    running, stalled = health["refreshing_sec"], state.get("stalled_sec")
    stuck = running is not None and running >= STUCK_REFRESH_SEC and (
        stalled is None or stalled >= STUCK_REFRESH_SEC)
    return {
        "as_of": _iso(state["as_of"]),
        "refreshing": running is not None or state["refreshing"],
        "refresh_running_sec": None if running is None else int(running),
        "phase": state["phase"],
        "progress": state["progress"],
        "refresh_failing": health["failing"] or not health["alive"] or stuck,
        "last_error": health["last_error"],
        "stale_after_sec": stale_after_min * 60,
    }


def freshness_key(fresh, now):
    """What of *fresh* changes what the dashboard shows at wall time *now*:
    its times by the minute, and what a refresh does only while the data is
    stale or the refresh failing (a fresh index's refreshes, one a second,
    leave its etag alone)."""
    if fresh is None:
        return None
    as_of, running, progress = (fresh[k] for k in ("as_of", "refresh_running_sec", "progress"))
    key = dict(fresh, as_of=as_of and as_of[:len("YYYY-MM-DDTHH:MM")],
               refresh_running_sec=None if running is None else running // 60,
               progress=None if progress is None else round(progress, 2))
    if as_of is not None and not fresh["refresh_failing"] and (
            now - datetime.datetime.fromisoformat(as_of).timestamp() <= fresh["stale_after_sec"]):
        for transient in ("refreshing", "refresh_running_sec", "phase", "progress"):
            del key[transient]
    return sorted(key.items())


def _iso(wall):
    if wall is None:
        return None
    return datetime.datetime.fromtimestamp(wall, datetime.timezone.utc).isoformat()
