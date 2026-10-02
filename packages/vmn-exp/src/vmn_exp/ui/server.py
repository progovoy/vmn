#!/usr/bin/env python3
"""FastAPI application for vmn-exp ui.

Reads go straight to the vmn library (lock-free); the SPA is served from
``static/`` when present. App names in URLs use vmn's dashed tag form
(``root_app/svc`` → ``root_app-svc``), which is bijective because ``-`` is
illegal in app names. Request hardening lives in :mod:`vmn_exp.ui.security`.
"""
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from vmn_exp.ui.auth.authz import require, require_action
from vmn_exp.ui.auth.principal import ADMIN, VIEWER
from vmn_exp.core.metric_schema import effective_schema
from vmn_exp.storage.files import FILE_TREES, valid_artifact_path
from vmn_exp.ui import (
    routes_leaderboard,
    routes_lineage,
    routes_media,
    routes_models,
    routes_series,
    routes_sweep,
    routes_tree,
)
from vmn_exp.ui.experiment_source import ExperimentSource
from vmn_exp.ui.http_params import attachment, clamp_page, key_list, media_type
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.memo import TTLCache
from vmn_exp.ui.middleware import SelectiveGZipMiddleware
from vmn_exp.ui.readers import changelog as changelog_reader
from vmn_exp.ui.readers import config as config_reader
from vmn_exp.ui.readers import diffs as diff_reader
from vmn_exp.ui.readers import experiment_detail as detail_reader
from vmn_exp.ui.readers import experiments as exp_reader
from vmn_exp.ui.refresher import InlineRefresher, Refresher
from vmn_exp.ui.responses import (
    GZIP_LEVEL,
    GZIP_MIN_BYTES,
    SafeJSONResponse,
    json_response,
)
from vmn_exp.ui.auth import build_chain
from vmn_exp.ui.security import RequestGuard, safe_app_name, safe_segment
from vmn_exp.ui.static_files import mount_static
from vmn_exp.storage.store_marker import require_store
from vmn_exp.ui.workspaces import WorkspaceError, workspace_storage

API_PREFIX = "/api/v1"
# A chart's worth of points per metric, however much a client asks for.
MAX_SERIES_POINTS = 20_000
# The app list walks .vmn/ and lists every app's runs: a few seconds stale is fine.
APPS_TTL_SEC = 5


def create_app(
    manager,
    token=None,
    read_only=False,
    use_index=True,
    bind_host=None,
    allowed_hosts=None,
    background_refresh=False,
    auth=None,
    role_mappings=(),
):
    """The FastAPI app. With *background_refresh* (what ``vmn-exp ui`` runs)
    watched apps' indexes are refreshed by daemon threads and requests serve
    the latest snapshot at once, up to about a second behind storage;
    without it each request refreshes the index first, seeing every write
    made before it. *auth* is an ``AuthenticatorChain`` tried after the
    static *token*; with neither the API is open. *role_mappings* map OIDC
    groups to roles (``{group, workspace or "*", role}``)."""
    from vmn_exp.storage.areas import RUNS
    from vmn_exp.storage.open import open_storage
    from vmn_exp.ui.jobs import JobRunner, build_command
    from vmn_exp.ui.jobs_store import build_store_action
    from vmn_exp.ui.storage_access import EDIT, probe_store

    app = FastAPI(
        title="vmn-exp ui",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        default_response_class=SafeJSONResponse,
    )
    app.state.manager = manager
    app.state.read_only = read_only
    app.state.role_mappings = list(role_mappings)
    jobs = JobRunner()
    chain = build_chain(token, auth.authenticators if auth else ())
    app.state.auth_chain = chain
    app.state.auth_enabled = bool(chain)
    guard = RequestGuard.build(
        bind_host=bind_host, allowed_hosts=allowed_hosts, token_required=bool(chain)
    )

    refresher = Refresher() if background_refresh else InlineRefresher()
    app.state.refresher = refresher
    source = ExperimentSource(manager.data_dir, use_index=use_index, refresher=refresher)
    leaderboards = LeaderboardCache()
    app_lists = TTLCache(APPS_TTL_SEC)
    # One client per store workspace: building one resolves credentials, and its
    # prefix probes are worth keeping across requests.
    store_storages = {}
    edit_storages = {}

    for router in chain.routers():
        app.include_router(router)

    @app.middleware("http")
    async def _authenticate(request: Request, call_next):
        # Off the event loop: API token checks run scrypt and hit the control plane.
        principal = await run_in_threadpool(chain.authenticate, request) if chain else None
        request.state.principal = principal
        if chain and principal is None and request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    # Registered after the token check, so it runs first: a rebound or
    # cross-site request is refused before anything else looks at it.
    @app.middleware("http")
    async def _request_guard(request: Request, call_next):
        refused = guard.reject_reason(
            request.method, request.url.path, request.headers
        )
        if refused:
            status, detail = refused
            return JSONResponse({"detail": detail}, status_code=status)
        return await call_next(request)

    app.add_middleware(
        SelectiveGZipMiddleware, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL
    )

    @app.exception_handler(ValueError)
    async def _bad_path(request: Request, exc: ValueError):
        # Storage refuses names that are not a single path component.
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def _app_name(app_tag):
        """The app name a URL names, refusing anything that walks out of .vmn/."""
        name = safe_app_name(app_tag)
        if name is None:
            raise HTTPException(400, f"Invalid app name '{app_tag}'")
        return name

    def _segment(value, what="version"):
        if not safe_segment(value):
            raise HTTPException(400, f"Invalid {what} '{value}'")
        return value

    def _optional_segment(value, what="version"):
        return None if value is None else _segment(value, what)

    def _workspace(name):
        ws = manager.get(name)
        if ws is None:
            raise HTTPException(404, f"Workspace '{name}' not found")
        return ws

    def _git_workspace(name):
        ws = _workspace(name)
        if ws.kind != "git":
            raise HTTPException(400, f"Workspace '{name}' is not a git checkout")
        return ws

    def _experiment_workspace(name):
        """Like _workspace but accepts git and store workspaces for experiment routes."""
        return _workspace(name)

    def _exp_storage_for(ws):
        """The store workspace's experiment storage (memoized), or None for git."""
        if ws.kind == "git":
            return None  # None means: use the default path-based reader
        if ws.name not in store_storages:
            try:
                storage = workspace_storage(ws)
                require_store(storage, ws.store)
                store_storages[ws.name] = storage
            except ValueError as exc:  # no store there / an unusable one
                raise HTTPException(404, str(exc))
        return store_storages[ws.name]

    def _any_exp_storage(ws):
        """The workspace's experiment storage, local checkout or store."""
        return _exp_storage_for(ws) or source.workspace_index(ws).storage

    @app.get(f"{API_PREFIX}/meta", dependencies=[require(VIEWER)])
    def meta():
        from version_stamp.api import version as version_mod

        return {"version": version_mod.version, "read_only": read_only}

    @app.get(f"{API_PREFIX}/workspaces", dependencies=[require(VIEWER)])
    def list_workspaces():
        return [ws.to_public_dict() for ws in manager.list()]

    @app.post(f"{API_PREFIX}/workspaces", status_code=201, dependencies=[require(ADMIN)])
    def add_workspace(body: dict):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        try:
            if body.get("remote"):
                ws = manager.clone_remote(
                    body["name"], body["remote"], path=body.get("path")
                )
            else:
                ws = manager.attach_path(body["name"], body["path"])
        except KeyError as e:
            raise HTTPException(422, f"Missing field: {e}")
        except WorkspaceError as e:
            raise HTTPException(400, str(e))
        return ws.to_public_dict()

    @app.delete(f"{API_PREFIX}/workspaces/{{ws_name}}", status_code=204, dependencies=[require(ADMIN)])
    def remove_workspace(ws_name: str):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        try:
            manager.remove(ws_name)
        except WorkspaceError as e:
            raise HTTPException(404, str(e))
        # A later workspace of the same name may point elsewhere.
        source.forget(ws_name)
        app_lists.pop(ws_name)
        store_storages.pop(ws_name, None)
        edit_storages.pop(ws_name, None)

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps", dependencies=[require(VIEWER)])
    def list_apps(ws_name: str):
        ws = _experiment_workspace(ws_name)
        store_storage = _exp_storage_for(ws)
        if store_storage:
            compute = lambda: exp_reader.list_apps_from_storage(store_storage)  # noqa: E731
        else:
            compute = lambda: exp_reader.list_apps(ws.path)  # noqa: E731
        return app_lists.get(ws_name, compute)

    def _leaderboard_inputs(ws_name, app_tag):
        """``(snapshot, effective metrics schema)`` of an app: rows summarized
        by the conf schema (none in a store), sorted by it plus what the runs
        declare (see :mod:`vmn_exp.core.metric_schema`)."""
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        schema = _app_schema(ws, app_name)
        snapshot = source.snapshot(ws, app_name, _exp_storage_for(ws), schema)
        return snapshot, effective_schema(schema, snapshot.declared_schema())

    def _app_schema(ws, app_name):
        """The app's conf.yml metrics schema; none in a store."""
        return {} if _exp_storage_for(ws) else source.metrics_schema(ws, app_name)

    def _detail_options(ws, app_name):
        """Refs, edges (and in the background, run states) from the app's snapshot."""
        return source.detail_options(ws, source.snapshot(ws, app_name, _exp_storage_for(ws)))

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}" "/experiments/{verstr}", dependencies=[require(VIEWER)])
    def get_experiment(
        request: Request,
        ws_name: str,
        app_tag: str,
        verstr: str,
        max_points: int = detail_reader.DEFAULT_MAX_POINTS,
        include_log: bool = False,
        keys: str = None,
        series: bool = True,
        x: str = None,
    ):
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        _segment(verstr)
        detail, err = exp_reader.get_experiment_from_storage(
            _any_exp_storage(ws),
            app_name,
            verstr,
            max_points=max(2, min(max_points, MAX_SERIES_POINTS)),
            include_log=include_log,
            keys=key_list(keys),
            include_series=series,
            x=x or None,
            schema=_app_schema(ws, app_name),
            **_detail_options(ws, app_name),
        )
        if err:
            raise HTTPException(404, err)
        return json_response(detail, request=request)

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}"
        "/experiments/{verstr}/log", dependencies=[require(VIEWER)])
    def experiment_log(
        request: Request,
        ws_name: str,
        app_tag: str,
        verstr: str,
        offset: int = 0,
        limit: int = detail_reader.LOG_TAIL,
    ):
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        _segment(verstr)
        offset, limit = clamp_page(offset, limit)
        page, err = detail_reader.log_page(
            _any_exp_storage(ws),
            app_name,
            verstr,
            offset=offset,
            limit=limit,
            read_log=exp_reader._load_log,
            # Inline, a snapshot costs a full refresh: more than resolving directly.
            resolve=(
                _detail_options(ws, app_name).get("resolve")
                if refresher.background
                else None
            ),
        )
        if err:
            raise HTTPException(404, err)
        return json_response(page, request=request)

    def download_artifact(ws_name: str, app_tag: str, verstr: str, filename: str):
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        _segment(verstr)
        # Record-relative paths (artifacts/a/b/c.txt), each part one segment.
        if not valid_artifact_path(filename):
            raise HTTPException(400, f"Invalid artifact name '{filename}'")
        download_name = filename.rsplit("/", 1)[-1]
        # The backend resolves the file — a local path, or an S3 object streamed
        # straight through — and refuses names that leave the run's dir.
        storage = _any_exp_storage(ws)
        opened = getattr(storage, "open_artifact", None)
        if opened:
            found = opened(app_name, verstr, filename)
            if found is None:
                raise HTTPException(404, f"Artifact {filename} not found")
            chunks, size = found
            return StreamingResponse(
                chunks,
                media_type=media_type(filename),
                headers={
                    "Content-Disposition": attachment(download_name),
                    "Content-Length": str(size),
                },
            )
        path = storage.artifact_local_path(app_name, verstr, filename)
        if not path or not os.path.isfile(path):
            raise HTTPException(404, f"Artifact {filename} not found")
        return FileResponse(path, filename=download_name)

    # A stored file's URL is its record path: .../experiments/{v}/artifacts/…
    # for the user's artifacts, .../experiments/{v}/outputs/… for vmn's own.
    def _download_route(tree):
        def download_from(ws_name: str, app_tag: str, verstr: str, path: str):
            return download_artifact(ws_name, app_tag, verstr, f"{tree}/{path}")

        app.get(
            f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}"
            f"/experiments/{{verstr}}/{tree}/{{path:path}}",
            name=f"download_{tree}",
            dependencies=[require(VIEWER)],
        )(download_from)

    for tree in FILE_TREES:
        _download_route(tree)

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/metrics-schema", dependencies=[require(VIEWER)])
    def app_metrics_schema(ws_name: str, app_tag: str):
        return _leaderboard_inputs(ws_name, app_tag)[1]

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/versions", dependencies=[require(VIEWER)])
    def list_versions(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return source.workspace_index(ws).list_versions(_app_name(app_tag))

    @app.post(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/actions/{{action}}",
        status_code=202, dependencies=[require_action()])
    def run_action(ws_name: str, app_tag: str, action: str, body: dict = None):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        ws = _workspace(ws_name)
        app_name = _app_name(app_tag)
        if ws.kind == "store":
            return _submit_store_action(ws, app_name, action, body)
        command, err = build_command(action, app_name, body)
        if err:
            raise HTTPException(400, err)
        job, err = jobs.submit(ws_name, ws.path, command)
        if err:
            raise HTTPException(409, err)
        return job

    def _capabilities(ws):
        if ws.capabilities is None:
            manager.set_capabilities(ws.name, probe_store(ws.store).capabilities)
        return ws.capabilities

    def _edit_storage(ws):
        if ws.name not in edit_storages:
            edit_storages[ws.name] = open_storage(ws.store, area=RUNS, buffer_logs=True)
        return edit_storages[ws.name]

    def _submit_store_action(ws, app_name, action, body):
        store_action, err = build_store_action(action, app_name, body)
        if err:
            raise HTTPException(400, err)
        if EDIT not in _capabilities(ws):
            raise HTTPException(403, "The server has no edit access to this store")
        storage, reads = _edit_storage(ws), _exp_storage_for(ws)

        def hint(app, verstr):
            source.touched(ws, app, reads)

        job, err = jobs.submit_call(
            ws.name, store_action.command, lambda: store_action.run(storage, hint))
        if err:
            raise HTTPException(409, err)
        return job

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}", dependencies=[require(VIEWER)])
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments-diff", dependencies=[require(VIEWER)])
    def experiments_diff(ws_name: str, app_tag: str, v: str, to: str):
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        _segment(v)
        _segment(to)
        store_storage = _exp_storage_for(ws)
        try:
            if store_storage:
                result, err = diff_reader.experiment_diff_from_storage(
                    store_storage, app_name, v, to
                )
            else:
                result, err = diff_reader.cached_experiment_diff(ws.path, app_name, v, to)
        except diff_reader.DiffBusy:
            raise HTTPException(429, "Too many diffs in progress; retry shortly")
        if err:
            raise HTTPException(404, err)
        return result

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/changelog", dependencies=[require(VIEWER)])
    def version_changelog(
        ws_name: str,
        app_tag: str,
        v: str = None,
        frm: str = Query(None, alias="from"),
    ):
        ws = _git_workspace(ws_name)
        result, err = changelog_reader.version_changelog(
            ws.path,
            _app_name(app_tag),
            to_verstr=_optional_segment(v),
            from_verstr=_optional_segment(frm),
        )
        if err:
            raise HTTPException(404, err)
        return result

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/config", dependencies=[require(VIEWER)])
    def app_config(ws_name: str, app_tag: str, v: str = None):
        ws = _git_workspace(ws_name)
        payload, err = config_reader.app_conf_payload(
            ws.path, _app_name(app_tag), verstr=_optional_segment(v)
        )
        if err:
            raise HTTPException(404, err)
        return payload

    def _series_storage(ws_name, app_tag):
        ws, app_name = _experiment_workspace(ws_name), _app_name(app_tag)
        return _any_exp_storage(ws), app_name, _app_schema(ws, app_name)

    def _workspace_lineage_inputs(ws_name):
        ws = _experiment_workspace(ws_name)
        store_storage = _exp_storage_for(ws)
        return lambda name: source.snapshot(ws, name, store_storage), _any_exp_storage(ws)

    def _lineage_inputs(ws_name, app_tag):
        return (_app_name(app_tag), *_workspace_lineage_inputs(ws_name))

    def _checkout(ws_name, app_tag):
        return _git_workspace(ws_name).path, _app_name(app_tag)

    routes_leaderboard.register(app, API_PREFIX, _leaderboard_inputs, leaderboards)
    routes_series.register(app, API_PREFIX, _series_storage, MAX_SERIES_POINTS)
    routes_media.register(app, API_PREFIX, _series_storage, _segment)
    routes_tree.register(app, API_PREFIX, _checkout, _optional_segment)
    routes_lineage.register(app, API_PREFIX, _lineage_inputs, _segment)
    routes_lineage.register_version_lineage(app, API_PREFIX, _workspace_lineage_inputs)
    routes_sweep.register(app, API_PREFIX, _lineage_inputs, _segment)
    routes_models.register(
        app, API_PREFIX,
        lambda ws_name: _any_exp_storage(_experiment_workspace(ws_name)),
    )
    mount_static(app, os.path.join(os.path.dirname(__file__), "static"))
    return app

