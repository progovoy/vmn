"""The server's meta, its workspaces and a workspace's apps."""
from fastapi import HTTPException, Request
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import ADMIN, VIEWER
from vmn_exp.ui.body_checks import workspace_fields
from vmn_exp.ui.shell_meta import workspace_role
from vmn_exp.ui.workspaces import WorkspaceError


def register(app, prefix, ctx, read_only, meta_of, forget):
    """Add the routes: *ctx* is the app's
    :class:`~vmn_exp.ui.server_context.ServerContext`, *meta_of(principal)*
    the ``/meta`` payload and *forget(ws_name)* drops what the server holds
    of a removed workspace."""
    manager = ctx.manager

    @app.get(f"{prefix}/meta", dependencies=[require(VIEWER)])
    def meta(request: Request):
        return meta_of(request.state.principal)

    @app.get(f"{prefix}/workspaces", dependencies=[require(VIEWER)])
    def list_workspaces(request: Request):
        principal = request.state.principal
        return [dict(ws.to_public_dict(), role=workspace_role(app.state, principal, ws.name))
                for ws in manager.list()]

    @app.post(f"{prefix}/workspaces", status_code=201, dependencies=[require(ADMIN)])
    def add_workspace(body: dict):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        name, remote, path = workspace_fields(body)
        try:
            if remote:
                ws = manager.clone_remote(name, remote, path=path)
            else:
                ws = manager.attach_path(name, path)
        except WorkspaceError as e:
            raise HTTPException(400, str(e))
        return ws.to_public_dict()

    @app.delete(f"{prefix}/workspaces/{{ws_name}}", status_code=204, dependencies=[require(ADMIN)])
    def remove_workspace(ws_name: str):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        try:
            manager.remove(ws_name)
        except WorkspaceError as e:
            raise HTTPException(404, str(e))
        # A later workspace of the same name may point elsewhere.
        forget(ws_name)

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps", dependencies=[require(VIEWER)])
    def list_apps(ws_name: str):
        return ctx.list_apps(ws_name)
