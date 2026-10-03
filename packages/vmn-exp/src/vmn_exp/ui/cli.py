#!/usr/bin/env python3
"""`vmn-exp ui` command: build the workspace registry from argv and serve.

The server never takes the repo lock — reads are lock-free and mutations run
as `vmn` CLI subprocesses that acquire it themselves.
"""
import dataclasses
import os
import re

from version_stamp.api import VMN_LOGGER
from vmn_exp.ui.security import LOOPBACK_HOSTS

DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".vmn-ui")


def _cwd_repo_root():
    """The enclosing repo of the current directory, or None."""
    path = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(path, ".git")) or os.path.isdir(
            os.path.join(path, ".vmn")
        ):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def _workspace_name(path):
    return os.path.basename(os.path.abspath(path)) or "workspace"


def build_manager(args, manager=None):
    """Create the WorkspaceManager for a `vmn-exp ui` invocation.

    Sources: every ``--repo`` path, a ``--store`` URI, and — when no
    explicit source is given — the repo enclosing the current directory.
    Re-attaching an already-registered source is a no-op.
    """
    from vmn_exp.ui.workspaces import WorkspaceError, WorkspaceManager

    if manager is None:
        manager = WorkspaceManager(args.data_dir or DEFAULT_DATA_DIR)

    registered_paths = {os.path.realpath(w.path) for w in manager.list() if w.path}

    repos = list(args.repo or [])
    store = getattr(args, "store", None)
    if not repos and not store:
        cwd_root = _cwd_repo_root()
        if cwd_root:
            repos.append(cwd_root)

    for path in repos:
        if os.path.realpath(path) in registered_paths:
            continue
        name = _workspace_name(path)
        suffix = 2
        while manager.get(name):
            name = f"{_workspace_name(path)}-{suffix}"
            suffix += 1
        try:
            manager.attach_path(name, path)
        except WorkspaceError as e:
            VMN_LOGGER.error(str(e))

    if store and store not in {w.store for w in manager.list()}:
        _add_store_workspace(manager, store)

    return manager


def _add_store_workspace(manager, uri):
    from vmn_exp.storage.uri import parse_store_uri

    parsed = parse_store_uri(uri)
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{parsed.scheme}-{parsed.location}").strip("-")
    name, suffix = base, 2
    while manager.get(name):
        name, suffix = f"{base}-{suffix}", suffix + 1
    manager.add_store(name, uri)


def open_control_plane(cfg):
    """The control plane a configured server keeps its state in."""
    from vmn_exp.ui.config import ConfigError
    from vmn_exp.ui.control_plane import SQLiteControlPlane
    from vmn_exp.ui.pg_mode import is_postgres_dsn

    if not cfg.db:
        return SQLiteControlPlane.in_data_dir(cfg.data_dir)
    if cfg.db.startswith("sqlite:///"):
        return SQLiteControlPlane(cfg.db[len("sqlite:///"):])
    if is_postgres_dsn(cfg.db):
        from vmn_exp.ui.control_plane_pg import PostgresControlPlane

        return PostgresControlPlane(cfg.db)
    raise ConfigError(
        f"Unsupported db {cfg.db!r}: use sqlite:///<path> or postgresql://...")


def postgres_dsn(cfg):
    """*cfg*'s Postgres DSN, or None (SQLite or no config)."""
    from vmn_exp.ui.pg_mode import is_postgres_dsn

    return cfg.db if cfg is not None and is_postgres_dsn(cfg.db) else None


def _enable_tenancy(cfg, control_plane):
    """Row-level security on, for ``tenancy: multi`` on Postgres."""
    if cfg.server.tenancy != "multi" or postgres_dsn(cfg) is None:
        return
    control_plane.enable_rls()


def seed_workspaces(manager, seeds):
    """Register config workspaces not yet in the registry (restarts keep edits)."""
    for seed in seeds:
        if manager.get(seed.name) is None:
            manager.add_store(seed.name, seed.store, downloads=seed.downloads,
                              reconcile_sec=seed.reconcile_sec)


def build_server(args, env=None):
    """``(manager, config, control_plane)``; config and control plane are
    ``None`` without ``--config``/``--db`` (the standalone server)."""
    from vmn_exp.ui.config import resolve_config
    from vmn_exp.ui.workspaces import DbWorkspaceRegistry, WorkspaceManager

    cfg = resolve_config(args, env=env)
    if cfg is None:
        return build_manager(args), None, None
    control_plane = open_control_plane(cfg)
    _enable_tenancy(cfg, control_plane)
    manager = WorkspaceManager(
        cfg.data_dir, registry=DbWorkspaceRegistry(control_plane),
        tenancy=cfg.server.tenancy, endpoint_allowlist=cfg.server.endpoint_allowlist,
    )
    seed_workspaces(manager, cfg.workspaces)
    if getattr(args, "repo", None) or getattr(args, "store", None):
        build_manager(args, manager)
    return manager, cfg, control_plane


def _oidc_chain(cfg, control_plane, env):
    from vmn_exp.ui.auth import AuthenticatorChain
    from vmn_exp.ui.auth.oidc import OIDCAuthenticator, OIDCConfig
    from vmn_exp.ui.config import ConfigError

    oidc = cfg.auth.oidc
    if oidc is None:
        return None
    if not cfg.server.public_url:
        raise ConfigError("auth.oidc needs server.public_url for its redirect URI")
    config = OIDCConfig(
        issuer=oidc.issuer,
        client_id=oidc.client_id,
        redirect_uri=cfg.server.public_url.rstrip("/") + "/auth/callback",
        client_secret=env.get(oidc.client_secret_env) if oidc.client_secret_env else None,
        groups_claim=oidc.groups_claim,
        role_mappings=[dataclasses.asdict(m) for m in cfg.auth.role_mappings],
    )
    return AuthenticatorChain([OIDCAuthenticator(config, control_plane)])


def server_app(manager, cfg, control_plane, args, env=None, token=None, **kwargs):
    """The FastAPI app for *manager*, with *cfg*'s auth wired in."""
    from vmn_exp.core.writer import set_default_writer_id
    from vmn_exp.ui.onboarding import SERVER_WRITER_ID
    from vmn_exp.ui.server import create_app

    env = os.environ if env is None else env
    # The server's own log writes match the edit policy's log/vmn-server*.
    set_default_writer_id(SERVER_WRITER_ID)
    dsn = postgres_dsn(cfg)
    auth = _oidc_chain(cfg, control_plane, env) if cfg else None
    host = cfg.server.host if cfg else args.host
    app = create_app(
        manager,
        token=token,
        read_only=args.read_only,
        use_index=not args.no_index,
        bind_host=host,
        allowed_hosts=getattr(args, "allowed_host", None),
        auth=auth,
        control_plane=control_plane,
        search_dsn=dsn,
        cache_dsn=dsn,
        **kwargs,
    )
    app.state.config = cfg
    app.state.role_mappings = cfg.auth.role_mappings if cfg else ()
    return app


def handle_ui(args):
    if getattr(args, "ui_args", None):
        if args.ui_args[0] == "onboarding":
            from vmn_exp.ui.onboarding_cli import handle_onboarding

            return handle_onboarding(args)
        if args.ui_args[0] != "cache":
            VMN_LOGGER.error(
                f"Unknown ui action {args.ui_args[0]!r} (use: cache, onboarding)")
            return 2
        from vmn_exp.ui.cache_cli import handle_cache

        return handle_cache(args)
    try:
        import uvicorn  # noqa: F401

        from vmn_exp.ui.server import create_app  # noqa: F401
    except ImportError:
        VMN_LOGGER.error(
            "The web UI requires the 'ui' extra. Install it with:\n\n"
            "  pip install 'vmn-exp[ui]'\n"
        )
        return 1

    from vmn_exp.ui.config import ConfigError

    try:
        manager, cfg, control_plane = build_server(args)
    except ConfigError as e:
        VMN_LOGGER.error(str(e))
        return 1
    host = cfg.server.host if cfg else args.host
    port = cfg.server.port if cfg else args.port
    token = cfg.token() if cfg else args.token or os.environ.get("VMN_UI_TOKEN")
    if host not in LOOPBACK_HOSTS and not token and not args.read_only:
        VMN_LOGGER.error(
            f"Refusing to bind {host} beyond localhost without --token: "
            "the Host-header allowlist is not authentication, so any host that "
            "can reach this port could forge it and get full read-write access. "
            "Pass --token (or set VMN_UI_TOKEN), pass --read-only to serve reads "
            "only, or bind --host to 127.0.0.1/localhost."
        )
        return 1
    if host not in LOOPBACK_HOSTS and not token:
        VMN_LOGGER.warning(
            "Binding beyond localhost without --token — --read-only keeps mutations "
            "blocked, but the Host-header allowlist is not authentication for reads."
        )

    try:
        app = server_app(manager, cfg, control_plane, args, token=token,
                         background_refresh=True)
    except ConfigError as e:
        VMN_LOGGER.error(str(e))
        return 1

    url = f"http://{host}:{port}"
    VMN_LOGGER.info(f"vmn-exp ui serving {len(manager.list())} workspace(s) at {url}")
    if not args.no_browser and host in ("127.0.0.1", "localhost"):
        import threading
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
