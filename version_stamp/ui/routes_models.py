"""FastAPI routes for the model registry.

All routes live under ``/api/v1/workspaces/{ws_name}/models/...``.
Mutations are executed in-process: the registry is git-free and needs no
per-repo lock.  The Origin / read-only guards run in the shared middleware
layer (``security.py``); this module adds name-level validation on top.
"""
from fastapi import HTTPException

from version_stamp.ui.jobs_models import (
    validate_alias_body,
    validate_register_body,
    validate_status_body,
)
from version_stamp.ui.readers.models import list_models_response, model_detail_response
from vmn_exp.registry.log import AliasConflict, remove_alias, set_alias, set_version_status
from vmn_exp.registry.names import valid_alias_name, valid_model_name
from vmn_exp.registry.store import register_version


def register(app, api_prefix, any_exp_storage):
    """Register model registry routes on *app*.

    *any_exp_storage(ws)* — a callable that takes a Workspace object and
    returns the experiment SnapshotStorage for that workspace.  This is the
    same helper used by experiment routes so the registry storage resolves
    identically.
    """
    base = f"{api_prefix}/workspaces/{{ws_name}}/models"

    def _storage(ws_name):
        return any_exp_storage(ws_name)

    def _valid_model(name: str) -> str:
        if not valid_model_name(name):
            raise HTTPException(400, f"Invalid model name {name!r}")
        return name

    def _valid_alias(name: str) -> str:
        if not valid_alias_name(name):
            raise HTTPException(400, f"Invalid alias name {name!r}")
        return name

    # ------------------------------------------------------------------
    # Read routes
    # ------------------------------------------------------------------

    @app.get(f"{base}")
    def list_models_route(ws_name: str):
        storage = _storage(ws_name)
        return list_models_response(storage)

    @app.get(f"{base}/{{model_name}}")
    def get_model_route(ws_name: str, model_name: str):
        _valid_model(model_name)
        storage = _storage(ws_name)
        detail, err = model_detail_response(storage, model_name)
        if err:
            raise HTTPException(404, err)
        return detail

    # ------------------------------------------------------------------
    # Mutation routes
    # ------------------------------------------------------------------

    def _require_rw():
        if app.state.read_only:
            raise HTTPException(403, "Server is read-only")

    @app.post(f"{base}/{{model_name}}/versions", status_code=201)
    def register_version_route(ws_name: str, model_name: str, body: dict = None):
        _require_rw()
        _valid_model(model_name)
        body = body or {}
        normalised, err = validate_register_body(body)
        if err:
            raise HTTPException(400, err)
        storage = _storage(ws_name)
        try:
            n = register_version(storage, model_name, normalised)
        except Exception as exc:
            raise HTTPException(500, str(exc))

        # Optional initial alias
        if normalised.get("alias"):
            try:
                set_alias(storage, model_name, normalised["alias"], n)
            except Exception:
                pass  # best-effort; version is already registered

        return {"version": n}

    @app.post(f"{base}/{{model_name}}/aliases", status_code=200)
    def move_alias_route(ws_name: str, model_name: str, body: dict = None):
        _require_rw()
        _valid_model(model_name)
        body = body or {}
        normalised, err = validate_alias_body(body)
        if err:
            raise HTTPException(400, err)
        storage = _storage(ws_name)
        try:
            set_alias(
                storage,
                model_name,
                normalised["alias"],
                normalised["version"],
                expect=normalised.get("expect"),
            )
        except AliasConflict as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {}

    @app.delete(f"{base}/{{model_name}}/aliases/{{alias}}", status_code=200)
    def remove_alias_route(ws_name: str, model_name: str, alias: str):
        _require_rw()
        _valid_model(model_name)
        _valid_alias(alias)
        storage = _storage(ws_name)
        try:
            remove_alias(storage, model_name, alias)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {}

    @app.post(f"{base}/{{model_name}}/versions/{{version_n}}/status", status_code=200)
    def set_status_route(ws_name: str, model_name: str, version_n: int, body: dict = None):
        _require_rw()
        _valid_model(model_name)
        body = body or {}
        status, err = validate_status_body(body)
        if err:
            raise HTTPException(400, err)
        storage = _storage(ws_name)
        try:
            set_version_status(storage, model_name, version_n, status)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {}
