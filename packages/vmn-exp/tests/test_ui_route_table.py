"""Characterization of the UI server's route table (plan 44 G6): FastAPI
matches routes in registration order and several paths overlap under
``.../apps/{app_tag}/...``, so moving routes out of server.py keeps the
ordered table exactly as it was."""
import dataclasses

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from vmn_exp.core.ports import IO
from vmn_exp.ui.app_deps import real_deps
from vmn_exp.ui.server import build_app
from vmn_exp.ui.workspaces import WorkspaceManager

WS = "/api/v1/workspaces/{ws_name}"
APP = WS + "/apps/{app_tag}"

GOLDEN = [
    ("/api/openapi.json", "GET HEAD"),
    ("/api/docs", "GET HEAD"),
    ("/docs/oauth2-redirect", "GET HEAD"),
    ("/redoc", "GET HEAD"),
    ("/api/v1/meta", "GET"),
    ("/api/v1/workspaces", "GET"),
    ("/api/v1/workspaces", "POST"),
    (WS, "DELETE"),
    (WS + "/apps", "GET"),
    (APP + "/experiments/{verstr}", "GET"),
    (APP + "/experiments/{verstr}/log", "GET"),
    (APP + "/experiments/{verstr}/artifacts/{path:path}", "GET"),
    (APP + "/experiments/{verstr}/outputs/{path:path}", "GET"),
    (APP + "/metrics-schema", "GET"),
    (APP + "/versions", "GET"),
    (APP + "/actions/{action}", "POST"),
    ("/api/v1/jobs/{job_id}", "GET"),
    (APP + "/experiments-diff", "GET"),
    (APP + "/changelog", "GET"),
    (APP + "/config", "GET"),
    ("/api/v1/tokens", "GET"),
    ("/api/v1/tokens", "POST"),
    ("/api/v1/tokens/{token_id}", "DELETE"),
    ("/api/v1/tokens", "DELETE"),
    ("/api/v1/audit", "GET"),
    ("/api/v1/audit/export", "GET"),
    (WS + "/cache/resync", "POST"),
    (WS + "/cache/status", "GET"),
    ("/metrics", "GET"),
    (APP + "/experiments", "GET"),
    (APP + "/experiments-columns", "GET"),
    (APP + "/experiments-importance", "GET"),
    (APP + "/experiments-facets", "GET"),
    (APP + "/experiments-pivot", "GET"),
    (APP + "/series", "POST"),
    (APP + "/experiments/{verstr}/metric-keys", "GET"),
    (APP + "/events", "GET"),
    (WS + "/git", "GET"),
    (APP + "/experiments-status", "GET"),
    (WS + "/apps-status", "GET"),
    (APP + "/search", "GET"),
    (APP + "/experiments/{verstr}/table/{path:path}", "GET"),
    (APP + "/experiments/{verstr}/histograms/{name:path}", "GET"),
    (APP + "/tree", "GET"),
    (APP + "/tree/root", "GET"),
    (APP + "/deps", "GET"),
    (APP + "/experiments/{verstr}/lineage", "GET"),
    (WS + "/models/{model_name}/versions/{n}/lineage", "GET"),
    (APP + "/experiments/{verstr}/summary", "GET"),
    (APP + "/experiments/{verstr}/failures", "GET"),
    (APP + "/experiments/{verstr}/baseline", "GET"),
    (APP + "/experiments-baselines", "GET"),
    (APP + "/experiments/{verstr}/sweep", "GET"),
    (APP + "/experiments/{verstr}/patch", "GET"),
    (APP + "/experiments/{verstr}/baselines", "GET"),
    (WS + "/models", "GET"),
    (WS + "/models/{model_name}", "GET"),
    (WS + "/models/{model_name}/versions", "POST"),
    (WS + "/models/{model_name}/aliases", "POST"),
    (WS + "/models/{model_name}/aliases/{alias}", "DELETE"),
    (WS + "/models/{model_name}/versions/{version_n}/status", "POST"),
    (WS + "/reports", "GET"),
    (APP + "/reports", "GET"),
    (WS + "/reports", "POST"),
    (WS + "/reports/{rid}", "GET"),
    (WS + "/reports/{rid}/revisions/{n}", "GET"),
    (WS + "/reports/{rid}/revisions/{n}/data/{panel}", "GET"),
    (WS + "/reports/{rid}/revisions", "POST"),
    (WS + "/reports/{rid}/publish", "POST"),
    (WS + "/reports/{rid}", "PATCH"),
    (WS + "/reports/{rid}", "DELETE"),
    (WS + "/comments", "GET"),
    (WS + "/comments", "POST"),
    (WS + "/comments/{target:path}/{comment_id}", "PATCH"),
    (WS + "/comments/{target:path}/{comment_id}", "DELETE"),
    (APP + "/settings", "GET"),
    (APP + "/settings", "PUT"),
    ("/api/v1/search", "GET"),
    (APP + "/experiments/{verstr}/similar", "GET"),
    (APP + "/similar", "GET"),
    ("/api/v1/similar", "GET"),
    ("/api/v1/diag", "GET"),
    ("/api/{rest:path}", "GET"),
]


def _route_table(app):
    return [(route.path, " ".join(sorted(getattr(route, "methods", None) or ())))
            for route in app.routes]


def _app(tmp_path, static_dir):
    io = IO(clock=FakeClock(), env=FakeEnv(), processes=FakeProcesses(),
            random=FakeRandom(), host=FakeHost(), console=FakeConsole())
    deps = real_deps(io, control_plane=None, background_refresh=False, read_only=False,
                     keep_warm=None)
    deps = dataclasses.replace(deps, static_dir=str(static_dir))
    return build_app(WorkspaceManager(str(tmp_path / "data")), deps)


def test_route_table_is_unchanged(tmp_path):
    app = _app(tmp_path, tmp_path / "no-bundle")

    assert _route_table(app) == GOLDEN


def test_a_built_bundle_mounts_its_assets_and_the_spa_after_every_api_route(tmp_path):
    bundle = tmp_path / "static"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>")

    app = _app(tmp_path, bundle)

    assert _route_table(app) == GOLDEN[:-1] + [("/assets", ""), ("/{full_path:path}", "GET")]
