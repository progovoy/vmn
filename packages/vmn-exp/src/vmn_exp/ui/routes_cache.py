"""Cache maintenance routes (plan 11 §4.6): ``POST .../cache/resync``
(``?full=1`` rebuilds), ``GET .../cache/status`` (both admin) and the
Prometheus-text ``/metrics`` with ``vmn_cache_drift_total``."""
from fastapi.responses import PlainTextResponse

from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import ADMIN, VIEWER


def _label(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def prometheus_text(caches):
    """``vmn_cache_drift_total`` per workspace, in the text exposition format."""
    lines = [
        "# HELP vmn_cache_drift_total Records the consistency check found changed"
        " without a journal entry.",
        "# TYPE vmn_cache_drift_total counter",
    ]
    for name, cache in sorted(caches.items()):
        lines.append(f'vmn_cache_drift_total{{workspace="{_label(name)}"}} {cache.status()["drift"]}')
    return "\n".join(lines) + "\n"


def register(app, api_prefix, cache_of, caches):
    """*cache_of(ws_name)* -> the workspace's ``WorkspaceCache`` (404 if
    unknown); *caches()* -> ``{name: WorkspaceCache}`` of every one in use."""
    base = f"{api_prefix}/workspaces/{{ws_name}}/cache"

    @app.post(f"{base}/resync", status_code=202, dependencies=[require(ADMIN)])
    def resync(ws_name: str, full: bool = False):
        return cache_of(ws_name).resync(full=full)

    @app.get(f"{base}/status", dependencies=[require(ADMIN)])
    def status(ws_name: str):
        return cache_of(ws_name).status()

    @app.get("/metrics", dependencies=[require(VIEWER)])
    def metrics():
        return PlainTextResponse(prometheus_text(caches()), media_type="text/plain; version=0.0.4")
