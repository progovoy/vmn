"""The HTTP API doc's endpoint tables list every route the server answers,
and every row names a route that exists (plan 42 E13).

A table is any markdown table whose header row starts ``| Method | Path |``.
Its paths are under ``/api/v1`` (written without it); a route outside
``/api/v1`` (``/metrics``, ``/auth/*``) is written with its full path."""
import os
import re

import pytest

pytest.importorskip("fastapi")

from exp_helpers import _PROJECT_ROOT

ENDPOINT_DOC = "docs/vmn-exp/ui-api.md"
API_PREFIX = "/api/v1"
TABLE_HEADER = "| Method | Path |"
# Framework pages and the JSON 404 catch-all: not endpoints a client calls.
EXCLUDED = {
    ("GET", "/api/openapi.json"),
    ("GET", "/api/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("GET", "/api/{rest:path}"),
}
_PARAM = re.compile(r"\{[^}]*\}")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _shape(path):
    return _PARAM.sub("{}", path.removeprefix(API_PREFIX))


def undocumented(routes, table_rows):
    """The (method, path) *routes* that no row of *table_rows* names,
    whatever either side calls its path parameters."""
    rows = {(method, _shape(path)) for method, path in table_rows}
    return sorted(r for r in set(routes) if (r[0], _shape(r[1])) not in rows)


def table_rows(text):
    """(method, path) of every row of every ``| Method | Path |`` table."""
    rows, in_table = [], False
    for line in text.splitlines():
        if line.startswith(TABLE_HEADER):
            in_table = True
        elif not line.startswith("|"):
            in_table = False
        elif in_table:
            rows += _row(line)
    return rows


def _row(line):
    cells = _CELL_SPLIT.split(line)[1:]
    methods = re.findall(r"`([A-Z]+)`", cells[0])
    path = re.search(r"`([^`]+)`", cells[1]) if len(cells) > 1 else None
    if not methods or path is None:
        return []
    bare = re.split(r"[?\[]", path.group(1))[0]
    return [(method, bare) for method in methods]


def test_undocumented_names_a_route_missing_from_the_rows():
    routes = [("GET", "/api/v1/meta"), ("GET", "/api/v1/jobs/{job_id}")]
    rows = [("GET", "/meta")]

    assert undocumented(routes, rows) == [("GET", "/api/v1/jobs/{job_id}")]


def test_undocumented_ignores_parameter_spelling():
    routes = [("GET", "/api/v1/workspaces/{ws_name}/apps/{app_tag}/experiments/{verstr}/artifacts/{path:path}")]
    rows = [("GET", "/workspaces/{ws}/apps/{app}/experiments/{verstr}/artifacts/{path}")]

    assert undocumented(routes, rows) == []


def test_undocumented_tells_methods_apart():
    assert undocumented([("POST", "/api/v1/tokens")], [("GET", "/tokens")]) == [
        ("POST", "/api/v1/tokens")]


def test_table_rows_reads_methods_and_bare_paths_of_method_path_tables():
    text = "\n".join([
        "| Method | Path | Answers |",
        "|---|---|---|",
        "| `GET` / `POST` | `/workspaces` | List / add |",
        "| `GET` | `/models[?kind=model\\|dataset]` | Models |",
        "| | `/workspaces/{ws}/models/...` | see below |",
        "",
        "| Flag | Default |",
        "| `GET` | `/not/a/route` |",
    ])

    assert table_rows(text) == [
        ("GET", "/workspaces"), ("POST", "/workspaces"), ("GET", "/models")]


def _walk(routes, prefix=""):
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:  # fastapi >= 0.140 keeps included routers nested
            yield from _walk(included.routes, prefix + route.include_context.prefix)
        else:
            yield prefix + route.path, route


def _app_routes(app):
    return {
        (method, path)
        for path, route in _walk(app.routes)
        for method in (getattr(route, "methods", None) or ()) if method != "HEAD"
    } - EXCLUDED


def _all_routes(tmp_path):
    """Routes of a plain app and of one with OIDC and a control plane,
    which add ``/auth/*``."""
    from vmn_exp.ui.auth import AuthenticatorChain
    from vmn_exp.ui.auth.oidc import OIDCAuthenticator, OIDCConfig
    from vmn_exp.ui.control_plane import SQLiteControlPlane
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    cp = SQLiteControlPlane(str(tmp_path / "cp.sqlite3"))
    config = OIDCConfig(issuer="https://idp.example", client_id="vmn-exp",
                        redirect_uri="https://vmn.example/auth/callback")
    oidc = OIDCAuthenticator(config, cp, object(), http=object())
    plain = create_app(WorkspaceManager(str(tmp_path / "plain")))
    with_auth = create_app(WorkspaceManager(str(tmp_path / "auth")),
                           auth=AuthenticatorChain([oidc]), control_plane=cp)
    return _app_routes(plain) | _app_routes(with_auth)


def _doc_rows():
    with open(os.path.join(_PROJECT_ROOT, ENDPOINT_DOC), encoding="utf-8") as f:
        return table_rows(f.read())


def test_every_route_is_documented(tmp_path):
    assert undocumented(_all_routes(tmp_path), _doc_rows()) == []


def test_documented_routes_exist(tmp_path):
    assert undocumented(_doc_rows(), _all_routes(tmp_path)) == []
