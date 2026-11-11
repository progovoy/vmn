"""One run's detail, log and stored files; an app's metrics schema and versions."""
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from vmn_exp.core.metric_schema import with_goal_counts, with_resolved_goals
from vmn_exp.storage.files import FILE_TREES, valid_artifact_path
from vmn_exp.ui import routes_media, routes_series
from vmn_exp.ui.api_errors import raise_read_error
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.http_params import attachment, clamp_page, key_list, media_type
from vmn_exp.ui.readers import experiment_detail as detail_reader
from vmn_exp.ui.readers import experiments as exp_reader
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.security import contained_artifact_path
from vmn_exp.ui.slow_reads import slow_read


def register(app, prefix, ctx, job_views, leaderboards, background, series_cap, is_file):
    """Add the routes: *ctx* is the app's
    :class:`~vmn_exp.ui.server_context.ServerContext`, *background* whether
    its refresher runs in the background, *series_cap* a series' points cap and
    *is_file(path)* checks a local artifact."""
    source = ctx.source
    app_path = f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"

    def _detail_options(ws, app_name):
        """Refs, edges (and in the background, run states) from the app's snapshot."""
        return source.detail_options(ws, source.snapshot(ws, app_name, ctx.exp_storage_for(ws)))

    @app.get(f"{app_path}/experiments/{{verstr}}", dependencies=[require(VIEWER)])
    @slow_read
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
        step_min: float = None,
        step_max: float = None,
    ):
        bounds = routes_series.step_range(step_min, step_max, x or None)
        ws = ctx.workspace(ws_name)
        app_name = ctx.app_name(app_tag)
        ctx.segment(verstr)
        detail, err = exp_reader.get_experiment_from_storage(
            ctx.any_exp_storage(ws),
            app_name,
            verstr,
            max_points=max(2, min(max_points, series_cap)),
            include_log=include_log,
            keys=key_list(keys),
            include_series=series,
            x=x or None,
            step_range=bounds,
            schema=ctx.app_schema(ws, app_name),
            job_status=lambda v: job_views.detail_status(*ctx.leaderboard_inputs(ws_name, app_tag), v),
            **_detail_options(ws, app_name),
        )
        if err:
            raise_read_error(err)
        return json_response(detail, request=request)

    @app.get(f"{app_path}/experiments/{{verstr}}/log", dependencies=[require(VIEWER)])
    @slow_read
    def experiment_log(
        request: Request,
        ws_name: str,
        app_tag: str,
        verstr: str,
        offset: int = 0,
        limit: int = detail_reader.LOG_TAIL,
    ):
        ws = ctx.workspace(ws_name)
        app_name = ctx.app_name(app_tag)
        ctx.segment(verstr)
        offset, limit = clamp_page(offset, limit)
        page, err = detail_reader.log_page(
            ctx.any_exp_storage(ws),
            app_name,
            verstr,
            offset=offset,
            limit=limit,
            read_log=exp_reader._load_log,
            # Inline, a snapshot costs a full refresh: more than resolving directly.
            resolve=_detail_options(ws, app_name).get("resolve") if background else None,
        )
        if err:
            raise_read_error(err)
        return json_response(page, request=request)

    def download_artifact(ws_name: str, app_tag: str, verstr: str, filename: str):
        ws = ctx.workspace(ws_name)
        app_name = ctx.app_name(app_tag)
        ctx.segment(verstr)
        # Record-relative paths (artifacts/a/b/c.txt), each part one segment.
        if not valid_artifact_path(filename):
            raise HTTPException(400, f"Invalid artifact name '{filename}'")
        redirect = routes_media.signed_redirect(ws, app_name, verstr, filename)
        if redirect is not None:
            return redirect
        download_name = filename.rsplit("/", 1)[-1]
        # The backend resolves the file — a local path, or an S3 object streamed
        # straight through — and refuses names that leave the run's dir.
        storage = ctx.any_exp_storage(ws)
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
        path = contained_artifact_path(storage, app_name, verstr, filename)
        if not path or not is_file(path):
            raise HTTPException(404, f"Artifact {filename} not found")
        return FileResponse(path, filename=download_name)

    # A stored file's URL is its record path: .../experiments/{v}/artifacts/…
    # for the user's artifacts, .../experiments/{v}/outputs/… for vmn's own.
    def _download_route(tree):
        def download_from(ws_name: str, app_tag: str, verstr: str, path: str):
            return download_artifact(ws_name, app_tag, verstr, f"{tree}/{path}")

        app.get(
            f"{app_path}/experiments/{{verstr}}/{tree}/{{path:path}}",
            name=f"download_{tree}",
            dependencies=[require(VIEWER)],
        )(slow_read(download_from))

    for tree in FILE_TREES:
        _download_route(tree)

    @app.get(f"{app_path}/metrics-schema", dependencies=[require(VIEWER)])
    def app_metrics_schema(ws_name: str, app_tag: str):
        snapshot, schema = ctx.leaderboard_inputs(ws_name, app_tag)
        names = leaderboards.facets(snapshot, archived=True)["metric_keys"]
        return with_goal_counts(with_resolved_goals(schema, names), snapshot.goal_counts())

    @app.get(f"{app_path}/versions", dependencies=[require(VIEWER)])
    def list_versions(ws_name: str, app_tag: str):
        ws = ctx.git_workspace(ws_name)
        return source.workspace_index(ws).list_versions(ctx.app_name(app_tag))
