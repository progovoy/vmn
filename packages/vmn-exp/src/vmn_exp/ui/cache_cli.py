#!/usr/bin/env python3
"""``vmn-exp ui cache resync|rebuild [--workspace <name>] [--config server.yml]``
(plan 11 §4.6).

Asks the running server (``server.host``/``port`` of the config, else
``--host``/``--port``) to resync each workspace — every one, or the
``--workspace`` named. When no server answers, it works on the cache files:
``rebuild`` deletes the workspace's cache database, so the next start
rebuilds it; ``resync`` has nothing to do, as every start reconciles fully.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from version_stamp.api import VMN_LOGGER

ACTIONS = ("resync", "rebuild")


def _post(url, token):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=b"{}", headers=headers, method="POST"), timeout=10) as r:
        return json.loads(r.read() or b"{}")


def _server(args):
    """``(manager, base url, token)`` of the invocation."""
    from vmn_exp.ui.cli import DEFAULT_DATA_DIR, build_server
    from vmn_exp.ui.workspaces import WorkspaceManager

    if getattr(args, "config", None) or getattr(args, "db", None):
        manager, cfg, _ = build_server(args)
        host, port, token = cfg.server.host, cfg.server.port, cfg.token()
    else:
        manager = WorkspaceManager(args.data_dir or DEFAULT_DATA_DIR)
        host, port = args.host, args.port
        token = args.token or os.environ.get("VMN_UI_TOKEN")
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return manager, f"http://{host}:{port}", token


def _cache_paths(manager, ws):
    from vmn_exp.ui import index as ui_index

    db_dir = os.path.join(manager.data_dir, "index")
    if ws.kind == "git":
        return [ui_index._db_path(db_dir, os.path.abspath(ws.path))]
    return [ui_index.s3_cache_path(db_dir, ws)]


def _offline(manager, ws, full):
    if not full:
        VMN_LOGGER.info(f"{ws.name}: no server running; its next start reconciles fully")
        return
    from vmn_exp.core.index_store import _remove_database

    for path in _cache_paths(manager, ws):
        _remove_database(path)
    VMN_LOGGER.info(f"{ws.name}: cache dropped; the next start rebuilds it")


def _resync(manager, base, token, ws, full):
    url = f"{base}/api/v1/workspaces/{quote(ws.name)}/cache/resync" + ("?full=1" if full else "")
    try:
        status = _post(url, token)
    except HTTPError as e:
        VMN_LOGGER.error(f"{ws.name}: the server refused ({e.code})")
        return 1
    except URLError:
        _offline(manager, ws, full)
        return 0
    VMN_LOGGER.info(f"{ws.name}: {'rebuild' if full else 'resync'} started"
                    f" ({status.get('state', 'requested')})")
    return 0


def handle_cache(args):
    rest = list(args.ui_args[1:])
    if len(rest) != 1 or rest[0] not in ACTIONS:
        VMN_LOGGER.error("usage: vmn-exp ui cache resync|rebuild [--workspace <name>]")
        return 2
    manager, base, token = _server(args)
    if args.workspace:
        ws = manager.get(args.workspace)
        if ws is None:
            VMN_LOGGER.error(f"Unknown workspace {args.workspace!r}")
            return 1
        workspaces = [ws]
    else:
        workspaces = manager.list()
    full = rest[0] == "rebuild"
    return max([_resync(manager, base, token, ws, full) for ws in workspaces], default=0)
