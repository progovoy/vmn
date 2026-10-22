#!/usr/bin/env python3
"""Warm every app's board when ``vmn-exp ui`` starts, off the request path.

The first open of a 100k-run app otherwise waits for the app's index to load
and then for the board's base to be built on that request (~6s). A daemon
thread started with the server loads each workspace's apps and builds their
bases; the refresher keeps them warm from then on (``on_refresh``).
``app.state.warmed`` is set once it is done (failures are logged, not raised).
"""
import logging
import threading

from vmn_exp.core.activity import activity

log = logging.getLogger(__name__)


def install(app, manager, list_apps, app_inputs, leaderboards, background):
    """Warm the apps on startup when *background* (the refresher runs); else
    there is nothing to warm and ``warmed`` is set at once."""
    app.state.warmed = threading.Event()
    if not background:
        app.state.warmed.set()
        return

    def warm_all():
        try:
            with activity("startup warmup"):
                for ws in manager.list():
                    _warm_workspace(ws.name, list_apps, app_inputs, leaderboards)
        finally:
            app.state.warmed.set()

    app.router.on_startup.append(
        lambda: threading.Thread(target=warm_all, name="vmn-ui-warmup", daemon=True).start())


def _warm_workspace(ws_name, list_apps, app_inputs, leaderboards):
    try:
        apps = list_apps(ws_name)
    except Exception:  # an unreachable store: its first request reports it
        log.debug("Warm-up skipped workspace %s", ws_name, exc_info=True)
        return
    for row in apps:
        try:
            leaderboards.warm(app_inputs(ws_name, row["name"])[1])
        except Exception:
            log.debug("Warm-up skipped %s/%s", ws_name, row.get("name"), exc_info=True)
