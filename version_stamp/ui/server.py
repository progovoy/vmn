#!/usr/bin/env python3
"""FastAPI application for vmn ui.

Reads go straight to the vmn library (lock-free); the SPA is served from
``static/`` when present. App names in URLs use vmn's dashed tag form
(``root_app/svc`` → ``root_app-svc``), which is bijective because ``-`` is
illegal in app names.
"""
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from version_stamp.core.version_math import tag_name_to_app_name
from version_stamp.ui.readers import changelog as changelog_reader
from version_stamp.ui.readers import config as config_reader
from version_stamp.ui.readers import diffs as diff_reader
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers import snapshots as snap_reader
from version_stamp.ui.readers import tree as tree_reader
from version_stamp.ui.readers import versions as ver_reader
from version_stamp.ui.workspaces import WorkspaceError

API_PREFIX = "/api/v1"


def create_app(manager, token=None, read_only=False, use_index=True):
    from version_stamp.ui.jobs import JobRunner, build_command

    app = FastAPI(title="vmn ui", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.manager = manager
    app.state.read_only = read_only
    jobs = JobRunner()

    indexes = {}

    def _index_for(ws):
        """Per-workspace read cache under the server data dir (never in the repo)."""
        if not use_index:
            return None
        if ws.name not in indexes:
            from version_stamp.ui.index import WorkspaceIndex

            indexes[ws.name] = WorkspaceIndex(
                ws.path, db_dir=os.path.join(manager.data_dir, "index")
            )
        return indexes[ws.name]

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
        index = _index_for(ws)
        if index:
            return index.list_experiments(app_name, sort=sort, last=last)
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
        index = _index_for(ws)
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
        app_name = tag_name_to_app_name(app_tag)
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
        ws = _git_workspace(ws_name)
        result, err = diff_reader.experiment_diff(
            ws.path, tag_name_to_app_name(app_tag), v, to
        )
        if err:
            raise HTTPException(404, err)
        return result

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/snapshots")
    def list_snapshots(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return snap_reader.list_snapshots(ws.path, tag_name_to_app_name(app_tag))

    @app.get(
        f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}"
        "/snapshots/{verstr}"
    )
    def get_snapshot(ws_name: str, app_tag: str, verstr: str):
        ws = _git_workspace(ws_name)
        detail, err = snap_reader.get_snapshot(
            ws.path, tag_name_to_app_name(app_tag), verstr
        )
        if err:
            raise HTTPException(404, err)
        return detail

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/tree")
    def version_tree(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return tree_reader.version_dag(ws.path, tag_name_to_app_name(app_tag))

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/tree/root")
    def root_tree(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return tree_reader.root_topology(ws.path, tag_name_to_app_name(app_tag))

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/changelog")
    def version_changelog(
        ws_name: str,
        app_tag: str,
        v: str = None,
        frm: str = Query(None, alias="from"),
    ):
        ws = _git_workspace(ws_name)
        result, err = changelog_reader.version_changelog(
            ws.path, tag_name_to_app_name(app_tag), to_verstr=v, from_verstr=frm
        )
        if err:
            raise HTTPException(404, err)
        return result

    @app.get(f"{API_PREFIX}/workspaces/{{ws_name}}/apps/{{app_tag}}/config")
    def app_config(ws_name: str, app_tag: str):
        ws = _git_workspace(ws_name)
        return config_reader.app_config(ws.path, tag_name_to_app_name(app_tag))

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
    if not os.path.isdir(static_dir):
        return

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(static_dir, "assets")),
        name="assets",
    )

    # History-API fallback: any non-API route is a client-side route — serve
    # the SPA shell and let the router resolve it.
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = os.path.join(static_dir, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(static_dir, "index.html"))
