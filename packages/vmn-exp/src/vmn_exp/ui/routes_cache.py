"""Cache maintenance routes (plan 11 §4.6): ``POST .../cache/resync``
(``?full=1`` rebuilds), ``GET .../cache/status`` (both admin) and the
Prometheus-text ``/metrics``: ``vmn_cache_drift_total``, then the apps'
rollup gauges (plan 28 T2a, :mod:`~vmn_exp.ui.metrics_feed`)."""
from fastapi.responses import PlainTextResponse

from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import ADMIN, VIEWER
from vmn_exp.ui.prometheus import Family, exposition


def prometheus_text(caches):
    """``vmn_cache_drift_total`` per workspace, in the text exposition format."""
    drift = Family("vmn_cache_drift_total", "counter",
                   "Records the consistency check found changed without a journal entry.")
    for name, cache in sorted(caches.items()):
        drift.add({"workspace": name}, cache.status()["drift"])
    return exposition([drift])


def register(app, api_prefix, cache_of, caches, gauges):
    """*cache_of(ws_name)* -> the workspace's ``WorkspaceCache`` (404 if
    unknown); *caches()* -> ``{name: WorkspaceCache}`` of every one in use;
    *gauges()* -> the rest of ``/metrics``' text."""
    base = f"{api_prefix}/workspaces/{{ws_name}}/cache"

    @app.post(f"{base}/resync", status_code=202, dependencies=[require(ADMIN)])
    def resync(ws_name: str, full: bool = False):
        return cache_of(ws_name).resync(full=full)

    @app.get(f"{base}/status", dependencies=[require(ADMIN)])
    def status(ws_name: str):
        return cache_of(ws_name).status()

    @app.get("/metrics", dependencies=[require(VIEWER)])
    def metrics():
        return PlainTextResponse(prometheus_text(caches()) + gauges(),
                                 media_type="text/plain; version=0.0.4")
