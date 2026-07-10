#!/usr/bin/env python3
"""FastAPI application for vmn ui.

Reads go straight to the vmn library (lock-free); the SPA is served from
``static/`` when present. App names in URLs use vmn's dashed tag form
(``root_app/svc`` → ``root_app-svc``), which is bijective because ``-`` is
illegal in app names.
"""
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from version_stamp.core.version_math import tag_name_to_app_name
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers import tree as tree_reader
from version_stamp.ui.readers import versions as ver_reader
from version_stamp.ui.workspaces import WorkspaceError

API_PREFIX = "/api/v1"


def create_app(manager, token=None, read_only=False):
    app = FastAPI(title="vmn ui", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.manager = manager
    app.state.read_only = read_only

    if token:
        @app.middleware("http")
        async def _token_auth(request: Request, call_next):
            if request.url.path.startswith("/api"):
                auth = request.headers.get("Authorization", "")
                if auth != f"Bearer {token}":
                    return JSONResponse(
                        {"detail": "Unauthorized"}, status_code=401
                    )
            return await call_next(request)

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

    @app.get(f"{API_PREFIX}/workspaces")
    def list_workspaces():
        return [ws.to_public_dict() for ws in manager.list()]

    @app.post(f"{API_PREFIX}/workspaces", status_code=201)
    def attach_workspace(body: dict):
        if read_only:
            raise HTTPException(403, "Server is read-only")
        try:
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

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps")
    def list_apps(ws_name: str):
        ws = _git_workspace(ws_name)
        return exp_reader.list_apps(ws.path)

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments")
    def list_experiments(ws_name: str, app_tag: str, sort: str = None,
                         last: int = None):
        ws = _git_workspace(ws_name)
        app_name = tag_name_to_app_name(app_tag)
        return exp_reader.list_experiments(ws.path, app_name, sort=sort, last=last)

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}"
        "/experiments/{verstr}"
    )
    def get_experiment(ws_name: str, app_tag: str, verstr: str):
        ws = _git_workspace(ws_name)
        app_name = tag_name_to_app_name(app_tag)
        detail, err = exp_reader.get_experiment(ws.path, app_name, verstr)
        if err:
            raise HTTPException(404, err)
        return detail

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/versions")
    def list_versions(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        app_name = tag_name_to_app_name(app_tag)
        return ver_reader.list_versions(ws.path, app_name)

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/tree")
    def version_tree(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return tree_reader.version_dag(ws.path, tag_name_to_app_name(app_tag))

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/tree/root")
    def root_tree(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return tree_reader.root_topology(ws.path, tag_name_to_app_name(app_tag))

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/deps")
    def dep_graph(ws_name: str, app_tag: str, v: str = None, to: str = None):
        ws = _git_workspace(ws_name)
        graph, err = tree_reader.dep_graph(
            ws.path, tag_name_to_app_name(app_tag), verstr=v, to_verstr=to
        )
        if err:
            raise HTTPException(404, err)
        return graph

    _mount_static(app)
    return app


def _mount_static(app):
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
