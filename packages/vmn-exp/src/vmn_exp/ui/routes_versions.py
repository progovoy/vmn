"""Between two versions: the runs' diff and the changelog; an app's config at a version."""
from fastapi import HTTPException, Query
from vmn_exp.ui.api_errors import error_body, raise_read_error
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.readers import changelog as changelog_reader
from vmn_exp.ui.readers import config as config_reader
from vmn_exp.ui.readers import diffs as diff_reader
from vmn_exp.ui.responses import SafeJSONResponse
from vmn_exp.ui.slow_reads import slow_read


def register(app, prefix, ctx):
    """Add the routes: *ctx* is the app's :class:`~vmn_exp.ui.server_context.ServerContext`."""
    source = ctx.source
    app_path = f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"

    @app.get(f"{app_path}/experiments-diff", dependencies=[require(VIEWER)])
    @slow_read
    def experiments_diff(ws_name: str, app_tag: str, v: str, to: str):
        ws = ctx.workspace(ws_name)
        app_name = ctx.app_name(app_tag)
        ctx.segment(v)
        ctx.segment(to)
        store_storage = ctx.exp_storage_for(ws)
        schema = ctx.app_schema(ws, app_name)
        try:
            if store_storage:
                # The index has both runs folded: no log read (a long-stuck
                # run's log is thousands of segments); else read the store.
                result, err = diff_reader.experiment_diff_from_snapshot(
                    source.snapshot(ws, app_name, store_storage, schema), v, to, schema), None
                if result is None:
                    result, err = diff_reader.experiment_diff_from_storage(
                        store_storage, app_name, v, to, schema=schema
                    )
            else:
                result, err = diff_reader.cached_experiment_diff(
                    ws.path, app_name, v, to, schema=schema, clock=ctx.clock
                )
        except diff_reader.DiffBusy:
            raise HTTPException(429, "Too many diffs in progress; retry shortly")
        except diff_reader.DiffMaterializeError as exc:
            return SafeJSONResponse(
                error_body(exc.detail, exc.reason, reason=exc.reason),
                status_code=422,
            )
        if err:
            raise_read_error(err)
        return result

    @app.get(f"{app_path}/changelog", dependencies=[require(VIEWER)])
    def version_changelog(
        ws_name: str,
        app_tag: str,
        v: str = None,
        frm: str = Query(None, alias="from"),
    ):
        ws = ctx.git_workspace(ws_name)
        result, err = changelog_reader.version_changelog(
            ws.path,
            ctx.app_name(app_tag),
            to_verstr=ctx.optional_segment(v),
            from_verstr=ctx.optional_segment(frm),
        )
        if err:
            raise HTTPException(404, err)
        return result

    @app.get(f"{app_path}/config", dependencies=[require(VIEWER)])
    def app_config(ws_name: str, app_tag: str, v: str = None):
        ws = ctx.git_workspace(ws_name)
        payload, err = config_reader.app_conf_payload(
            ws.path, ctx.app_name(app_tag), verstr=ctx.optional_segment(v)
        )
        if err:
            raise HTTPException(404, err)
        return payload
