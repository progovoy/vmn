#!/usr/bin/env python3
"""FastAPI application for vmn ui.

Reads go straight to the vmn library (lock-free); the SPA is served from
``static/`` when present. App names in URLs use vmn's dashed tag form
(``root_app/svc`` → ``root_app-svc``), which is bijective because ``-`` is
illegal in app names. Request hardening lives in :mod:`version_stamp.ui.security`.
"""
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.cli.snapshot_storage_files import valid_artifact_path
from version_stamp.ui import routes_leaderboard, routes_series, routes_tree
from version_stamp.ui.experiment_source import ExperimentSource
from version_stamp.ui.http_params import attachment, clamp_page, key_list
from version_stamp.ui.leaderboard_cache import LeaderboardCache
from version_stamp.ui.memo import TTLCache
from version_stamp.ui.middleware import SelectiveGZipMiddleware, bearer_matches
from version_stamp.ui.readers import changelog as changelog_reader
from version_stamp.ui.readers import config as config_reader
from version_stamp.ui.readers import diffs as diff_reader
from version_stamp.ui.readers import experiment_detail as detail_reader
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers import snapshots as snap_reader
from version_stamp.ui.readers import versions as ver_reader
from version_stamp.ui.refresher import Refresher
from version_stamp.ui.responses import (
    GZIP_LEVEL,
    GZIP_MIN_BYTES,
    SafeJSONResponse,
    json_response,
)
from version_stamp.ui.security import RequestGuard, safe_app_name, safe_segment
from version_stamp.ui.static_files import mount_static
from version_stamp.ui.workspaces import WorkspaceError

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
):
    """The FastAPI app. With *background_refresh* (what ``vmn ui`` runs)
    watched apps' indexes are refreshed by daemon threads and requests serve
    the latest snapshot at once, up to about a second behind storage;
    without it each request refreshes the index first, seeing every write
    made before it."""
    from version_stamp.ui.jobs import JobRunner, build_command

    app = FastAPI(
        title="vmn ui",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        default_response_class=SafeJSONResponse,
    )
    app.state.manager = manager
    app.state.read_only = read_only
    jobs = JobRunner()
    guard = RequestGuard.build(
        bind_host=bind_host, allowed_hosts=allowed_hosts, token_required=bool(token)
    )

    refresher = Refresher() if background_refresh else None
    app.state.refresher = refresher
    source = ExperimentSource(manager.data_dir, use_index=use_index, refresher=refresher)
    leaderboards = LeaderboardCache()
    app_lists = TTLCache(APPS_TTL_SEC)
    # One client per S3 workspace: building one resolves credentials, and its
    # prefix probes are worth keeping across requests.
    s3_storages = {}

    if token:

        @app.middleware("http")
        async def _token_auth(request: Request, call_next):
            if request.url.path.startswith("/api"):
                if not bearer_matches(request.headers.get("Authorization"), token):
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
        """Like _workspace but accepts git, s3, and path-only workspaces for experiment routes."""
        return _workspace(name)

    def _exp_storage_for(ws):
        """The workspace's S3 experiment storage (memoized), or None for git."""
        if ws.kind != "s3":
            return None  # None means: use the default path-based reader
        if ws.name not in s3_storages:
            s3_storages[ws.name] = get_snapshot_storage(
                "s3",
                bucket=ws.bucket,
                prefix=ws.prefix or "vmn-experiments",
                endpoint_url=ws.endpoint_url,
                subdir="experiments",
            )
        return s3_storages[ws.name]

    def _any_exp_storage(ws):
        """The workspace's experiment storage, local checkout or S3."""
        return _exp_storage_for(ws) or exp_reader.experiment_storage(ws.path)

    @app.get(f"{API_PREFIX}/meta")
    def meta():
        from version_stamp import version as version_mod

        return {"version": version_mod.version}

    @app.get(f"{API_PREFIX}/workspaces")
    def list_workspaces():
        return [ws.to_public_dict() for ws in manager.list()]

    @app.post(f"{API_PREFIX}/workspaces", status_code=201)
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

    @app.delete(f"{API_PREFIX}/workspaces/{{ws_name}}", status_code=204)
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
        s3_storages.pop(ws_name, None)

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps")
    def list_apps(ws_name: str):
        ws = _experiment_workspace(ws_name)
        s3_storage = _exp_storage_for(ws)
        if s3_storage:
            compute = lambda: exp_reader.list_apps_from_storage(s3_storage)  # noqa: E731
        else:
            compute = lambda: exp_reader.list_apps(ws.path)  # noqa: E731
        return app_lists.get(ws_name, compute)

    def _leaderboard_inputs(ws_name, app_tag):
        """``(snapshot, metrics schema)`` of an app; no app conf on S3."""
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        s3_storage = _exp_storage_for(ws)
        snapshot = source.list_snapshot(ws, app_name, s3_storage)
        schema = {} if s3_storage else source.metrics_schema(ws, app_name)
        return snapshot, schema

    def _detail_options(ws, app_name):
        """Refs, edges and run states from the app's snapshot when indexed."""
        return source.detail_options(ws, source.snapshot(ws, app_name, _exp_storage_for(ws)))

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}" "/experiments/{verstr}"
    )
    def get_experiment(
        request: Request,
        ws_name: str,
        app_tag: str,
        verstr: str,
        max_points: int = detail_reader.DEFAULT_MAX_POINTS,
        include_log: bool = False,
        keys: str = None,
        series: bool = True,
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
            **_detail_options(ws, app_name),
        )
        if err:
            raise HTTPException(404, err)
        return json_response(detail, request=request)

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}"
        "/experiments/{verstr}/log"
    )
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
            resolve=_detail_options(ws, app_name).get("resolve") if refresher else None,
        )
        if err:
            raise HTTPException(404, err)
        return json_response(page, request=request)

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}"
        "/experiments/{verstr}/artifacts/{filename:path}"
    )
    def download_artifact(ws_name: str, app_tag: str, verstr: str, filename: str):
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        _segment(verstr)
        # Nested artifacts are relative paths (a/b/c.txt), each part one segment.
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
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": attachment(download_name),
                    "Content-Length": str(size),
                },
            )
        path = storage.artifact_local_path(app_name, verstr, filename)
        if not path or not os.path.isfile(path):
            raise HTTPException(404, f"Artifact {filename} not found")
        return FileResponse(path, filename=download_name)

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/metrics-schema")
    def app_metrics_schema(ws_name: str, app_tag: str):
        ws = _experiment_workspace(ws_name)
        s3_storage = _exp_storage_for(ws)
        if s3_storage:
            return {}  # No app conf available for S3 workspaces
        return source.metrics_schema(ws, _app_name(app_tag))

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/versions")
    def list_versions(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        app_name = _app_name(app_tag)
        index = source.workspace_index(ws)
        if index:
            return index.list_versions(app_name)
        return ver_reader.list_versions(ws.path, app_name)

    @app.post(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/actions/{{action}}",
        status_code=202,
    )
    def run_action(ws_name: str, app_tag: str, action: str, body: dict = None):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        ws = _git_workspace(ws_name)
        app_name = _app_name(app_tag)
        command, err = build_command(action, app_name, body)
        if err:
            raise HTTPException(400, err)
        job, err = jobs.submit(ws_name, ws.path, command)
        if err:
            raise HTTPException(409, err)
        return job

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments-diff")
    def experiments_diff(ws_name: str, app_tag: str, v: str, to: str):
        ws = _experiment_workspace(ws_name)
        app_name = _app_name(app_tag)
        _segment(v)
        _segment(to)
        s3_storage = _exp_storage_for(ws)
        try:
            if s3_storage:
                result, err = diff_reader.experiment_diff_from_storage(
                    s3_storage, app_name, v, to
                )
            else:
                result, err = diff_reader.cached_experiment_diff(ws.path, app_name, v, to)
        except diff_reader.DiffBusy:
            raise HTTPException(429, "Too many diffs in progress; retry shortly")
        if err:
            raise HTTPException(404, err)
        return result

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/snapshots")
    def list_snapshots(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return snap_reader.list_snapshots(ws.path, _app_name(app_tag))

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}" "/snapshots/{verstr}"
    )
    def get_snapshot(ws_name: str, app_tag: str, verstr: str):
        ws = _git_workspace(ws_name)
        detail, err = snap_reader.get_snapshot(
            ws.path, _app_name(app_tag), _segment(verstr)
        )
        if err:
            raise HTTPException(404, err)
        return detail

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/changelog")
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

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/config")
    def app_config(ws_name: str, app_tag: str, v: str = None):
        ws = _git_workspace(ws_name)
        payload, err = config_reader.app_conf_payload(
            ws.path, _app_name(app_tag), verstr=_optional_segment(v)
        )
        if err:
            raise HTTPException(404, err)
        return payload

    def _series_storage(ws_name, app_tag):
        return _any_exp_storage(_experiment_workspace(ws_name)), _app_name(app_tag)

    def _checkout(ws_name, app_tag):
        return _git_workspace(ws_name).path, _app_name(app_tag)

    routes_leaderboard.register(app, API_PREFIX, _leaderboard_inputs, leaderboards)
    routes_series.register(app, API_PREFIX, _series_storage, MAX_SERIES_POINTS)
    routes_tree.register(app, API_PREFIX, _checkout, _optional_segment)
    mount_static(app, os.path.join(os.path.dirname(__file__), "static"))
    return app

