"""What ``vmn_exp.ui.server.build_app`` serves with: the collaborators it does
not build itself, and the IO they were built from (plan 44 G4).
``real_deps`` builds the real ones; tests hand ``build_app`` their own."""
import asyncio
import os
from dataclasses import dataclass
from typing import Any

from vmn_exp.core.ports import IO, wall_seconds
from vmn_exp.core.status import min_stale_sec
from vmn_exp.ui.audit import AuditLog
from vmn_exp.ui.auth.tokens import TokenService
from vmn_exp.ui.jobs import JobRunner, start_daemon
from vmn_exp.ui.refresher import InlineRefresher, Refresher
from vmn_exp.ui.store_upkeep import StoreUpkeep


@dataclass(frozen=True)
class ServerDeps:
    io: IO
    jobs: Any  # JobRunner
    refresher: Any  # Refresher or InlineRefresher
    upkeep: Any  # StoreUpkeep, or None: the server writes no markers or compaction
    audit: Any  # AuditLog, or None without a control plane
    token_service: Any  # TokenService, or None without a control plane
    event_sleep: Any  # async sleep(sec) between a live-event stream's ticks
    status_clock: Any  # the Clock run statuses are derived at and the indexes run on
    static_dir: str  # the web bundle served at / (absent: the API alone)


def real_deps(io, control_plane, background_refresh, read_only, keep_warm):
    """The collaborators ``vmn-exp ui`` serves with, on *io*'s clock. With
    *background_refresh* (what ``vmn-exp ui`` runs) watched apps' indexes are
    refreshed by daemon threads and requests serve the latest snapshot at
    once, up to about a second behind storage; without it each request
    refreshes the index first, seeing every write made before it. *keep_warm*
    keeps a background-refreshed index refreshing with nobody watching (None:
    store workspaces' indexes only; see :mod:`~vmn_exp.ui.refresher`). A
    *control_plane* gets an audit log and API tokens; a background, writable
    server writes the markers and compaction a store lacks itself."""
    wall = wall_seconds(io.clock)
    refresher = (Refresher(keep_warm=keep_warm, clock=io.clock.monotonic)
                 if background_refresh else InlineRefresher())
    return ServerDeps(
        io=io,
        jobs=JobRunner(processes=io.processes, random=io.random, start_thread=start_daemon),
        refresher=refresher,
        upkeep=(StoreUpkeep(clock=io.clock.monotonic, now=io.clock.now,
                            min_stale_sec=min_stale_sec(io.env))
                if background_refresh and not read_only else None),
        audit=AuditLog(control_plane, clock=wall, random=io.random) if control_plane else None,
        token_service=TokenService(control_plane, clock=wall, random=io.random) if control_plane else None,
        event_sleep=asyncio.sleep,
        status_clock=io.clock,
        static_dir=os.path.join(os.path.dirname(__file__), "static"),
    )
