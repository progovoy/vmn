"""The dashboard's request mix, as the web UI (``webui/src/api*.ts``) sends it.

Each builder takes the shared :class:`Vocabulary` and a ``random.Random`` and
returns a :class:`Call`. Page sizes and point counts mirror the UI's constants:
leaderboard pages of 200 (``paging.ts``), chart columns capped at 10_000 rows
(``useChartRows.ts``), log pages of 500 (``RunLog.tsx``), overlay series at
1000 points (``overlaySeries.ts``); run detail is fetched without parameters
(server default ``max_points``/log tail), exactly like ``api.experiment``.
"""
import dataclasses
import threading
from urllib.parse import quote

PAGE_SIZE = 200
CHART_ROW_LIMIT = 10_000
LOG_PAGE = 500
OVERLAY_POINTS = 1000
POOL_CAP = 2000

# Route family before the dot selects the SLO budget (see slo.py).
WEIGHTS = {
    "list.first": 20,
    "list.sort_metric": 8,
    "list.sort_ts": 6,
    "list.deep": 6,
    "list.query": 8,
    "list.status": 6,
    "list.recent": 3,
    "facets": 5,
    "columns": 5,
    "detail": 15,
    "detail.log": 5,
    "series": 5,
}
# Driven by the freshness loop, not the weighted mix.
LIVE_ROUTE = "list.live"
ROUTES = (*WEIGHTS, LIVE_ROUTE)


@dataclasses.dataclass
class Call:
    route: str
    method: str
    path: str
    params: dict = None
    body: dict = None


class Vocabulary:
    """What the mix picks from: metric/param keys (from facets), the list
    total, and a bounded pool of verstrs seen in list responses."""

    def __init__(self):
        self.metric_keys = []
        self.param_keys = []
        self.total = 0
        self._verstrs = []
        self._seen = set()
        self._lock = threading.Lock()

    def learn_rows(self, rows, total=None):
        if total is not None:
            self.total = total
        with self._lock:
            for row in rows:
                v = row.get("verstr")
                if v and v not in self._seen and len(self._verstrs) < POOL_CAP:
                    self._seen.add(v)
                    self._verstrs.append(v)

    def learn_facets(self, facets):
        self.metric_keys = [k for k in facets.get("metric_keys", []) if k != "probe_ts"] or ["probe_ts"]
        self.param_keys = list(facets.get("param_keys", []))
        self.total = facets.get("total", self.total)

    def verstrs(self, rng, n):
        with self._lock:
            pool = list(self._verstrs)
        return rng.sample(pool, min(n, len(pool)))


def _field(prefix, key):
    return f'{prefix}."{key}"'


def _page(**extra):
    return {"offset": 0, "limit": PAGE_SIZE, **extra}


def _queries(voc, rng):
    m = _field("metrics", rng.choice(voc.metric_keys))
    out = [
        'status = "failed"',
        'status in ("running", "stuck")',
        f"{m} < 0.5",
        f'{m} > 0 and status = "succeeded"',
        'name ~ "live"',
    ]
    if voc.param_keys:
        p = _field("params", rng.choice(voc.param_keys))
        out += [f"not {p} = null", f"{p} != null and {m} >= 0"]
    return out


def _detail_path(ws_app, verstr, suffix=""):
    return f"{ws_app}/experiments/{quote(verstr, safe='')}{suffix}"


def build(route, ws_app, voc, rng):
    """The :class:`Call` for *route*, or None when the vocabulary can't feed
    it yet (no run seen, for the per-run routes)."""
    base = f"{ws_app}/experiments"
    if route == "list.first":
        return Call(route, "GET", base, _page())
    if route == "list.sort_metric":
        order = rng.choice([None, "asc", "desc"])
        params = _page(sort=rng.choice(voc.metric_keys))
        return Call(route, "GET", base, params if order is None else dict(params, order=order))
    if route == "list.sort_ts":
        return Call(route, "GET", base, _page(sort="timestamp", order="desc"))
    if route == "list.deep":
        pages = max(voc.total // PAGE_SIZE, 1)
        return Call(route, "GET", base, _page(offset=rng.randrange(pages) * PAGE_SIZE))
    if route == "list.query":
        return Call(route, "GET", base, _page(q=rng.choice(_queries(voc, rng))))
    if route == "list.status":
        return Call(route, "GET", base, _page(status=rng.choice(["running,stuck", "failed", "succeeded"])))
    if route == "list.recent":
        return Call(route, "GET", base, {"offset": 0, "last": 20, "limit": 20})
    if route == "facets":
        return Call(route, "GET", f"{ws_app}/experiments-facets")
    if route == "columns":
        keys = [f"metrics.{k}" for k in voc.metric_keys[:2]]
        keys += [f"params.{k}" for k in voc.param_keys[:1]] + ["status"]
        return Call(route, "GET", f"{ws_app}/experiments-columns",
                    {"keys": ",".join(keys), "limit": CHART_ROW_LIMIT})
    return _per_run(route, ws_app, voc, rng)


def _per_run(route, ws_app, voc, rng):
    picked = voc.verstrs(rng, rng.randint(2, 8) if route == "series" else 1)
    if not picked:
        return None
    if route == "detail":
        return Call(route, "GET", _detail_path(ws_app, picked[0]))
    if route == "detail.log":
        return Call(route, "GET", _detail_path(ws_app, picked[0], "/log"), {"offset": 0, "limit": LOG_PAGE})
    if route == "series":
        body = {"verstrs": picked, "keys": None, "max_points": OVERLAY_POINTS}
        return Call(route, "POST", f"{ws_app}/series", body=body)
    raise KeyError(route)


def live_call(ws_app):
    """The freshness read: running rows, freshest ``probe_ts`` first."""
    params = {"offset": 0, "limit": 50, "status": "running", "sort": "probe_ts", "order": "desc"}
    return Call(LIVE_ROUTE, "GET", f"{ws_app}/experiments", params)
