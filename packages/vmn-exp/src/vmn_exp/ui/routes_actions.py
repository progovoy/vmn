"""Job actions on an app's runs (one run, or the runs of a query) and a job's state."""
from functools import partial

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from vmn_exp.core.query import QueryError
from vmn_exp.ui.auth.authz import can_read_job, require, require_action
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.bulk_actions import BulkSpec, is_bulk
from vmn_exp.ui.jobs import build_command
from vmn_exp.ui.jobs_store import build_store_action
from vmn_exp.ui.leaderboard_scope import UnknownScope
from vmn_exp.ui.pending_edits import ship_pending_first
from vmn_exp.ui.storage_access import EDIT


def register(app, prefix, ctx, jobs, leaderboards, read_only, io):
    """Add the routes: *ctx* is the app's
    :class:`~vmn_exp.ui.server_context.ServerContext`, *jobs* its job runner."""

    @app.post(
        f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/actions/{{action}}",
        status_code=202, dependencies=[require_action()])
    def run_action(ws_name: str, app_tag: str, action: str, body: dict = None):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        ws = ctx.workspace(ws_name)
        app_name = ctx.app_name(app_tag)
        if is_bulk(action, body):
            return _bulk_action(ws, app_tag, app_name, action, body)
        if ws.kind == "store":
            return _submit_store_action(ws, app_name, action, body)
        command, err = build_command(action, app_name, body)
        if err:
            raise HTTPException(400, err)
        job, err = jobs.submit(ws_name, ws.path, command)
        if err:
            raise HTTPException(409, err)
        return job

    def _bulk_action(ws, app_tag, app_name, action, body):
        """An action on the runs of a query (plan 23 S4): a ``dry_run``
        preview, else a batched job resolving them again when it starts."""
        spec, err = BulkSpec.build(action, app_name, body)
        if err:
            raise HTTPException(400, err)
        ctx.optional_segment(body.get("scope"))
        if ws.kind == "store" and EDIT not in ctx.capabilities(ws):
            raise HTTPException(403, "The server has no edit access to this store")

        def resolve():
            snapshot, schema = ctx.leaderboard_inputs(ws.name, app_tag)
            filters = spec.filters(leaderboards.now())
            return spec.matching(leaderboards.ordered(snapshot, schema, **filters))

        try:
            verstrs = resolve()
        except UnknownScope as e:
            raise HTTPException(404, str(e))
        except QueryError as e:
            raise HTTPException(400, str(e))
        if body.get("dry_run"):
            return JSONResponse(spec.preview(verstrs))
        if ws.kind == "store":
            storage, reads = ctx.edit_storage(ws), ctx.exp_storage_for(ws)
            apply = partial(spec.apply, storage, hint=lambda app, v: ctx.source.touched(ws, app, reads),
                            now=leaderboards.now(), env=io.env, host=io.host)

            def act(batch):
                return ship_pending_first(storage, partial(apply, batch))
        else:
            act = partial(spec.run_in_checkout, jobs.run_command, ws.path)
        job, err = jobs.submit_bulk(ws.name, spec.label, resolve, act)
        if err:
            raise HTTPException(409, err)
        return job

    def _submit_store_action(ws, app_name, action, body):
        store_action, err = build_store_action(action, app_name, body, io.env, io.host)
        if err:
            raise HTTPException(400, err)
        if EDIT not in ctx.capabilities(ws):
            raise HTTPException(403, "The server has no edit access to this store")
        storage, reads = ctx.edit_storage(ws), ctx.exp_storage_for(ws)

        def hint(app, verstr):
            ctx.source.touched(ws, app, reads)

        job, err = jobs.submit_call(ws.name, store_action.command, lambda: ship_pending_first(
            storage, lambda: store_action.run(storage, hint, leaderboards.now())))
        if err:
            raise HTTPException(409, err)
        return job

    @app.get(f"{prefix}/jobs/{{job_id}}", dependencies=[require(VIEWER)])
    def get_job(job_id: str, request: Request):
        # 404, not 403, for another workspace's or org's job: an id is never confirmed.
        scoped = jobs.get_scoped(job_id)
        if scoped is None or not can_read_job(request, *scoped[1:]):
            raise HTTPException(404, "Job not found")
        return scoped[0]
