"""FastAPI routes for an app's store settings (plan 28 A0).

``GET/PUT /api/v1/workspaces/{ws}/apps/{app}/settings``: the
``settings/<app-key>/app/experiment.yml`` file as written plus what it
parses to and who wrote it last. Reads need ``viewer``, writes ``editor``
(like reports and comments); writes are refused under ``--read-only``.
"""
from fastapi import HTTPException, Request

from vmn_exp.core.app_settings import SettingsError, parse_settings
from vmn_exp.core.app_settings_store import (
    read_settings_text,
    settings_metadata,
    write_settings,
)
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import EDITOR, VIEWER
from vmn_exp.ui.request_author import author_of


def _payload(storage, app_name):
    text = read_settings_text(storage, app_name) or ""
    try:
        settings, error = parse_settings(text), None
    except SettingsError as exc:
        settings, error = {}, str(exc)
    return dict(settings_metadata(storage, app_name), text=text, settings=settings,
                error=error)


def register(app, api_prefix, settings_target):
    """*settings_target(ws_name, app_tag)* -> ``(storage, app name, changed())``,
    *changed* telling the server's caches the settings moved."""
    path = f"{api_prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/settings"

    @app.get(path, dependencies=[require(VIEWER)])
    def get_settings(ws_name: str, app_tag: str):
        storage, app_name, _ = settings_target(ws_name, app_tag)
        return _payload(storage, app_name)

    @app.put(path, dependencies=[require(EDITOR)])
    def put_settings(ws_name: str, app_tag: str, request: Request, body: dict = None):
        if app.state.read_only:
            raise HTTPException(403, "Server is read-only")
        text = (body or {}).get("text")
        if not isinstance(text, str):
            raise HTTPException(400, "text must be a string")
        storage, app_name, changed = settings_target(ws_name, app_tag)
        try:
            write_settings(storage, app_name, text, actor=author_of(request))
        except SettingsError as exc:
            raise HTTPException(400, str(exc))
        changed()
        return _payload(storage, app_name)
