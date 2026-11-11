#!/usr/bin/env python3
"""FastAPI application for vmn-exp ui.

Reads go straight to the vmn library (lock-free); the SPA is served from
``static/`` when present. App names in URLs use vmn's dashed tag form
(``root_app/svc`` → ``root_app-svc``), which is bijective because ``-`` is
illegal in app names. Request hardening lives in :mod:`vmn_exp.ui.security`;
the resolvers routes share in :mod:`vmn_exp.ui.server_context`.
"""
import os
from functools import partial

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from vmn_exp.core.app_conf import read_experiment_conf
from vmn_exp.core.similar_search import conf_weights
from vmn_exp.ui.api_errors import error_body, status_code_name
from vmn_exp.ui.app_presence import app_exists
from vmn_exp.ui.attention_built_in import with_built_in
from vmn_exp.ui.app_deps import real_deps, wall_seconds
from vmn_exp.ui.audit import install_audit_middleware
from vmn_exp.ui.auth import build_chain
from vmn_exp.ui.auth.tokens import ApiTokenAuthenticator
from vmn_exp.ui.config import DEFAULT_AUDIT_RETENTION_DAYS, DEFAULT_METRICS_ENDED_HOURS
from vmn_exp.ui.experiment_source import ExperimentSource
from vmn_exp.ui.baseline_views import BaselineViews
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.memo import TTLCache
from vmn_exp.ui.metrics_feed import MetricsFeed
from vmn_exp.ui.middleware import SelectiveGZipMiddleware
from vmn_exp.ui.query_params import refuse_unknown_params
from vmn_exp.ui.readers.models import ModelListing
from vmn_exp.ui.registry_snapshot import RegistryListings, RegistrySnapshot, RegistrySnapshots
from vmn_exp.ui.report_index import ReportIndexes
from vmn_exp.ui.responses import GZIP_LEVEL, GZIP_MIN_BYTES, SafeJSONResponse
from vmn_exp.ui.security import RequestGuard
from vmn_exp.ui.server_context import ServerContext
from vmn_exp.ui.settings_cache import request_scope
from vmn_exp.ui.shell_meta import auth_hints, meta_payload
from vmn_exp.ui.static_files import mount_static
from vmn_exp.ui.tenancy import install_org_middleware
from vmn_exp.ui.thread_limiters import install_default_limiter
from vmn_exp.ui.workspaces import workspace_storage

from vmn_exp.ui import (
    api_errors,
    diag,
    control_plane_sweep,
    routes_actions,
    routes_admin,
    routes_baseline,
    routes_cache,
    routes_comments,
    routes_events,
    routes_experiment,
    routes_job,
    routes_leaderboard,
    routes_lineage,
    routes_media,
    routes_models,
    routes_pivot,
    routes_reports,
    routes_run_code,
    routes_run_search,
    routes_search,
    routes_series,
    routes_settings,
    routes_shell,
    routes_similar,
    routes_sweep,
    routes_tree,
    routes_versions,
    routes_workspaces,
    startup_warmup,
)
from vmn_exp.ui.diag import routes as diag_routes

API_PREFIX = "/api/v1"
# A chart's worth of points per metric, however much a client asks for.
MAX_SERIES_POINTS = 20_000
# The app list walks .vmn/ and lists every app's runs: a few seconds stale is fine.
APPS_TTL_SEC = 5


class SettingsScope:
    """Inline refresh re-reads apps' settings once per request, not per read
    path. Plain ASGI: a BaseHTTPMiddleware leaves cyclic garbage per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        with request_scope():
            await self.app(scope, receive, send)


def create_app(manager, io, background_refresh=False, keep_warm=None, read_only=False,
               control_plane=None, **options):
    """``build_app`` with the collaborators :func:`~vmn_exp.ui.app_deps.real_deps` builds on *io*."""
    deps = real_deps(io, control_plane, background_refresh, read_only, keep_warm)
    return build_app(manager, deps, read_only=read_only, control_plane=control_plane, **options)


def build_app(
    manager,
    deps,
    token=None,
    read_only=False,
    use_index=True,
    bind_host=None,
    allowed_hosts=None,
    auth=None,
    role_mappings=(),
    control_plane=None,
    search_dsn=None,
    cache_dsn=None,
    audit_retention_days=DEFAULT_AUDIT_RETENTION_DAYS,
    metrics_ended_hours=DEFAULT_METRICS_ENDED_HOURS,
):
    """The FastAPI app, serving with *deps*' job runner, refresher, store
    upkeep, audit log and token service (:class:`~vmn_exp.ui.app_deps.ServerDeps`).
    *auth* is an ``AuthenticatorChain`` tried after the static *token*; with
    neither the API is open. *role_mappings* map OIDC groups to roles
    (``{group, workspace or "*", role}``). A *control_plane* enables API
    tokens (``vmnx_...`` bearer tokens, managed under ``/api/v1/tokens``) and
    the audit log, kept *audit_retention_days* by its hourly sweep
    (:mod:`~vmn_exp.ui.control_plane_sweep`). A Postgres *search_dsn* answers
    ``/api/v1/search`` in SQL; a Postgres *cache_dsn* caches store
    workspaces' indexes there, refreshed by one elected replica. An ended
    outer run stays on ``/metrics`` for *metrics_ended_hours*
    (:mod:`~vmn_exp.ui.metrics_feed`)."""
    from vmn_exp.storage.areas import RUNS
    from vmn_exp.storage.open import open_storage

    from vmn_exp.ui import storage_access

    app = FastAPI(
        title="vmn-exp ui",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        default_response_class=SafeJSONResponse,
        dependencies=[refuse_unknown_params(API_PREFIX)],
    )
    app.router.on_startup.append(install_default_limiter)  # first: before any thread runs
    app.state.manager, app.state.read_only = manager, read_only
    app.state.role_mappings = list(role_mappings)
    jobs = app.state.jobs = deps.jobs
    app.state.control_plane = control_plane
    app.state.audit, app.state.token_service = deps.audit, deps.token_service
    if control_plane:
        control_plane_sweep.install(app, control_plane, audit_retention_days, wall_seconds(deps.io.clock))
    extra = list(auth.authenticators) if auth else []
    if deps.token_service:
        extra.append(ApiTokenAuthenticator(deps.token_service))
    chain = build_chain(token, extra)
    app.state.auth_chain = chain
    app.state.auth_enabled = bool(chain)
    guard = RequestGuard.build(
        bind_host=bind_host, allowed_hosts=allowed_hosts, token_required=bool(chain)
    )

    refresher = app.state.refresher = deps.refresher
    search_sql = search_rows = None
    if search_dsn:
        from vmn_exp.ui.search_pg import PgRowSearch
        from vmn_exp.ui.search_rows_writer import SearchRowsWriter

        search_sql = PgRowSearch(search_dsn)
        search_rows = SearchRowsWriter(search_sql)
    upkeep = app.state.store_upkeep = deps.upkeep
    source = ExperimentSource(manager.data_dir, use_index=use_index, refresher=refresher,
                              cache_dsn=cache_dsn, search_rows=search_rows,
                              store_upkeep=upkeep, clock=deps.io.clock, processes=deps.io.processes)
    # Looked up at call time, so a test's patch of this module or of
    # storage_access/storage.open still applies.
    ctx = ServerContext(
        manager, source, TTLCache(APPS_TTL_SEC),
        open_workspace_storage=lambda ws: workspace_storage(ws),
        open_edit_storage=lambda uri: open_storage(uri, area=RUNS, buffer_logs=True),
        probe_store=lambda uri: storage_access.probe_store(uri),
        app_exists=lambda *args: app_exists(*args),
    )
    leaderboards = LeaderboardCache(conf_of=ctx.board_conf)
    if refresher.background:  # requests after a refresh pay no base or search build
        refresher.on_refresh = leaderboards.warm
    job_views = JobViews(leaderboards)
    report_indexes = ReportIndexes(
        os.path.join(manager.data_dir, "index") if use_index else None, refresher.background,
        journal_of=source.journal_of,
    )

    for router in chain.routers():
        app.include_router(router)

    install_audit_middleware(app)
    install_org_middleware(app, getattr(manager, "tenancy", "single"))

    app.add_middleware(SettingsScope)

    def _principal(request):
        if diag_routes.is_diag_request(API_PREFIX, request.url.path):
            return diag_routes.authenticate(chain, request)
        return run_in_threadpool(chain.authenticate, request)

    @app.middleware("http")
    async def _authenticate(request: Request, call_next):
        # Off the event loop: API token and session checks hit the control plane.
        principal = await _principal(request) if chain else None
        request.state.principal = principal
        if chain and principal is None and request.url.path.startswith("/api"):
            return JSONResponse(error_body("Unauthorized", "unauthorized", auth=auth_hints(chain)),
                                status_code=401, headers={"WWW-Authenticate": "Bearer"})
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
            return JSONResponse(error_body(detail, status_code_name(status)), status_code=status)
        return await call_next(request)

    app.add_middleware(
        SelectiveGZipMiddleware, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL
    )

    api_errors.install(app)

    def _forget(ws_name):
        for forget in (source.forget, report_indexes.forget, ctx.forget, forget_git):
            forget(ws_name)

    routes_workspaces.register(app, API_PREFIX, ctx, read_only,
                               lambda principal: meta_payload(app.state, principal, read_only),
                               _forget)
    routes_experiment.register(app, API_PREFIX, ctx, job_views, leaderboards, refresher.background,
                               MAX_SERIES_POINTS, os.path.isfile)
    routes_actions.register(app, API_PREFIX, ctx, jobs, leaderboards, read_only)
    routes_versions.register(app, API_PREFIX, ctx)

    group_aggregate = ctx.from_settings(source.group_aggregate)
    split_by = ctx.from_settings(source.split_by)
    experiment_ui = ctx.from_settings(source.experiment_ui)
    views = ctx.from_settings(source.views)
    attention_entries = ctx.from_settings(lambda *app_args: with_built_in(source.attention(*app_args)))
    freshness = ctx.from_settings(lambda ws, app_name, settings: source.freshness(
        ws.name, app_name, source.stale_after_min(ws, app_name, settings)))
    leaderboard_inputs = ctx.leaderboard_inputs

    def _similar_weights(ws_name, app_name):
        """The app's conf.yml ``experiment.similar.weights``, read as ``vmn-exp
        similar`` and the SDK reader read them; none in a store."""
        ws = ctx.workspace(ws_name)
        if ctx.exp_storage_for(ws):
            return None
        return conf_weights(read_experiment_conf(app_name, ws.path))

    def _series_storage(ws_name, app_tag):
        ws, app_name = ctx.workspace(ws_name), ctx.app_name(app_tag)
        return ctx.any_exp_storage(ws), app_name, ctx.app_schema(ws, app_name)

    def _workspace_lineage_inputs(ws_name):
        ws = ctx.workspace(ws_name)
        store_storage = ctx.exp_storage_for(ws)
        return lambda name: source.snapshot(ws, name, store_storage), ctx.any_exp_storage(ws)

    def _lineage_inputs(ws_name, app_tag):
        return (ctx.app_name(app_tag), *_workspace_lineage_inputs(ws_name))

    def _checkout(ws_name, app_tag):
        return ctx.git_workspace(ws_name).path, ctx.app_name(app_tag)

    routes_admin.register(app, API_PREFIX, wall_seconds(deps.io.clock))

    def _cache_of(ws_name):
        ws = ctx.workspace(ws_name)
        if ws.kind == "git":
            source.workspace_index(ws)
        return source.cache(ws)

    app.state.metrics_feed = MetricsFeed(source, manager.get, leaderboards, metrics_ended_hours)
    routes_cache.register(app, API_PREFIX, _cache_of, source.caches, app.state.metrics_feed.text)

    def _report_index(ws_name):
        ws = ctx.workspace(ws_name)
        return report_indexes.get(ws, ctx.any_exp_storage(ws))

    def _comment_counts(ws_name, app_tag):
        index = _report_index(ws_name)
        return index.comment_counts(ctx.app_name(app_tag)), index.generation

    routes_leaderboard.register(app, API_PREFIX, leaderboard_inputs, leaderboards,
                                _comment_counts, group_aggregate, attention_entries,
                                experiment_ui)
    routes_pivot.register(app, API_PREFIX, leaderboard_inputs, leaderboards, group_aggregate)
    routes_series.register(app, API_PREFIX, _series_storage, MAX_SERIES_POINTS)

    def _events_reader(ws_name, app_tag):
        ws, app_name = ctx.workspace(ws_name), ctx.app_name(app_tag)
        return partial(source.snapshot, ws, app_name, ctx.exp_storage_for(ws))

    routes_events.register(app, API_PREFIX, _events_reader, refresher.background, ctx.segment,
                           deps.io.clock.monotonic, deps.event_sleep)
    forget_git = routes_shell.register(
        app, API_PREFIX, ctx.git_workspace, ctx.status_snapshot, ctx.app_tags, leaderboards,
        freshness, attention_entries, ctx.status_schema, views, experiment_ui,
        processes=deps.io.processes)
    routes_run_search.register(app, API_PREFIX, ctx.status_snapshot, leaderboards)
    routes_media.register(app, API_PREFIX, _series_storage, ctx.segment)
    routes_tree.register(app, API_PREFIX, _checkout, ctx.optional_segment, deps.io.processes)
    listings = RegistryListings(deps.io.clock.monotonic)  # one listing per refresh for both
    registries, model_lists = (RegistrySnapshots(refresher.background, read, listings,
                                                 clock=deps.io.clock.monotonic)
                               for read in (RegistrySnapshot.read, ModelListing.read))
    routes_lineage.register(app, API_PREFIX, _lineage_inputs, ctx.segment, registries.get)
    routes_lineage.register_version_lineage(app, API_PREFIX, _workspace_lineage_inputs,
                                            registries.get)
    routes_job.register(app, API_PREFIX, leaderboard_inputs, job_views, ctx.segment, split_by)
    routes_baseline.register(app, API_PREFIX, leaderboard_inputs, BaselineViews(job_views),
                             ctx.segment, attention_entries)
    routes_sweep.register(app, API_PREFIX, _lineage_inputs, ctx.segment,
                          lambda ws_name, app_tag, verstr: job_views.job_summary(
                              *leaderboard_inputs(ws_name, app_tag), verstr))
    routes_run_code.register(app, API_PREFIX, _series_storage, leaderboard_inputs,
                             leaderboards, ctx.segment)
    routes_models.register(app, API_PREFIX, ctx.ws_storage, model_lists)
    routes_reports.register(app, API_PREFIX, ctx.ws_storage, _report_index)
    routes_comments.register(app, API_PREFIX, ctx.ws_storage)

    def _settings_target(ws_name, app_tag):
        app_name = ctx.app_name(app_tag)
        changed = lambda: source.settings_changed(ctx.workspace(ws_name), app_name)  # noqa: E731
        return ctx.ws_storage(ws_name), app_name, changed

    routes_settings.register(app, API_PREFIX, _settings_target)

    def _search_scopes(ws_names):
        return ((ws, name, snap) for ws, name, snap, _ in ctx.app_scopes(ws_names))

    routes_search.register(app, API_PREFIX, _search_scopes, search_sql)
    routes_similar.register(app, API_PREFIX, ctx.app_inputs, ctx.app_scopes, ctx.segment,
                            _similar_weights, source.similar.scope)
    startup_warmup.install(app, manager, ctx.list_apps, ctx.app_inputs, leaderboards,
                           refresher.background)
    diag.install_app(app, API_PREFIX, refresher)
    mount_static(app, os.path.join(os.path.dirname(__file__), "static"))
    return app
