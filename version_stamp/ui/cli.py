#!/usr/bin/env python3
"""`vmn ui` command: build the workspace registry from argv and serve.

The server never takes the repo lock — reads are lock-free and mutations run
as `vmn` CLI subprocesses that acquire it themselves.
"""
import os

from version_stamp.core.logging import VMN_LOGGER

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


def build_manager(args):
    """Create the WorkspaceManager for a `vmn ui` invocation.

    Sources: every ``--repo`` path, an ``--s3-bucket`` source, and — when no
    explicit source is given — the repo enclosing the current directory.
    Re-attaching an already-registered source is a no-op.
    """
    from version_stamp.ui.workspaces import WorkspaceError, WorkspaceManager

    data_dir = args.data_dir or DEFAULT_DATA_DIR
    manager = WorkspaceManager(data_dir)

    registered_paths = {
        os.path.realpath(w.path) for w in manager.list() if w.path
    }
    registered_buckets = {
        (w.bucket, w.prefix) for w in manager.list() if w.kind == "s3"
    }

    repos = list(args.repo or [])
    if not repos and not args.s3_bucket:
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

    if args.s3_bucket and (args.s3_bucket, args.s3_prefix) not in registered_buckets:
        name = f"s3-{args.s3_bucket}"
        if not manager.get(name):
            manager.add_s3(
                name, args.s3_bucket,
                prefix=args.s3_prefix, endpoint_url=args.endpoint_url,
            )

    return manager


def handle_ui(args):
    try:
        import uvicorn  # noqa: F401
        from version_stamp.ui.server import create_app
    except ImportError:
        VMN_LOGGER.error(
            "The web UI requires the 'ui' extra. Install it with:\n\n"
            "  pip install vmn[ui]\n"
        )
        return 1

    manager = build_manager(args)
    token = args.token or os.environ.get("VMN_UI_TOKEN")
    if args.host not in ("127.0.0.1", "localhost") and not token:
        VMN_LOGGER.warning(
            "Binding beyond localhost without --token — the API is unauthenticated."
        )

    app = create_app(
        manager, token=token, read_only=args.read_only,
        use_index=not args.no_index,
    )

    url = f"http://{args.host}:{args.port}"
    VMN_LOGGER.info(f"vmn ui serving {len(manager.list())} workspace(s) at {url}")
    if not args.no_browser and args.host in ("127.0.0.1", "localhost"):
        import threading
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0
