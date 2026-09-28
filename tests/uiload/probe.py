"""HTTP load / latency / freshness prober for the ``vmn-exp ui`` API.

``Probe(base_url, ws, app).run(duration_sec, concurrency)`` replays the
dashboard's request mix (:mod:`uiload.probe_routes`) from a thread pool and
returns a :class:`~uiload.probe_stats.Report`. GETs repeat with
``If-None-Match`` once their URL answered an ETag, so the report counts 304s.

Freshness: a side loop reads the running rows sorted by the ``probe_ts``
metric (live workers log ``time.time()`` there every step, and list rows carry
each run's latest metric values under ``metrics``); ``now - max(probe_ts)`` is
how far the dashboard lags behind the writers.
"""
import logging
import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

from uiload import probe_routes
from uiload.probe_routes import ROUTES, WEIGHTS
from uiload.probe_stats import Report, Sample, build_report  # noqa: F401

API = "/api/v1"
# Per-request DEBUG traces from thousands of probe requests drown any report.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
MAX_PAGE = 1000
TIMEOUT_SEC = 30


def _ms_since(started):
    return (time.perf_counter() - started) * 1000


def _headers(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def _client(base_url, token):
    return httpx.Client(base_url=base_url.rstrip("/") + API, headers=_headers(token), timeout=TIMEOUT_SEC)


def _app_tag(app):
    return app.replace("/", "-")


def app_path(ws, app):
    """``/workspaces/<ws>/apps/<tag>`` — the API prefix of one app (under ``/api/v1``)."""
    return f"/workspaces/{ws}/apps/{_app_tag(app)}"


class Probe:
    def __init__(self, base_url, ws=None, app=None, token=None, seed=None):
        self.base_url = base_url
        self.ws, self.app, self.token = ws, app, token
        self.voc = probe_routes.Vocabulary()
        self._rng_seed = seed
        self._etags = {}

    def discover(self):
        """``(ws, app)``: the given ones, else the first workspace/app served."""
        with _client(self.base_url, self.token) as c:
            if self.ws is None:
                self.ws = c.get("/workspaces").raise_for_status().json()[0]["name"]
            if self.app is None:
                self.app = c.get(f"/workspaces/{self.ws}/apps").raise_for_status().json()[0]["name"]
        return self.ws, self.app

    @property
    def _ws_app(self):
        return app_path(self.ws, self.app)

    def _warm_up(self, client):
        """Fill the vocabulary: facets for keys, a first page for verstrs."""
        self.voc.learn_facets(client.get(f"{self._ws_app}/experiments-facets").raise_for_status().json())
        page = client.get(f"{self._ws_app}/experiments", params={"offset": 0, "limit": MAX_PAGE})
        body = page.raise_for_status().json()
        self.voc.learn_rows(body["rows"], body["total"])

    def _send(self, client, call):
        """Issue *call*; returns ``(Sample, json body or None)``."""
        request = client.build_request(call.method, call.path, params=call.params, json=call.body)
        url = str(request.url)
        etag = self._etags.get(url) if call.method == "GET" else None
        if etag:
            request.headers["If-None-Match"] = etag
        started = time.perf_counter()
        try:
            resp = client.send(request)
        except httpx.HTTPError as e:
            return Sample(call.route, _ms_since(started), None, 0, bool(etag), error=repr(e)), None
        ms = _ms_since(started)
        if resp.headers.get("etag") and call.method == "GET":
            self._etags[url] = resp.headers["etag"]
        # Only list bodies are read back; parsing the rest (columns: ~0.5MB)
        # would hold the GIL and inflate the other probe threads' timings.
        wanted = resp.status_code == 200 and call.route.startswith("list.")
        body = resp.json() if wanted else None
        return Sample(call.route, ms, resp.status_code, resp.num_bytes_downloaded, bool(etag)), body

    def _learn(self, route, body):
        if isinstance(body, dict) and route.startswith("list.") and "rows" in body:
            self.voc.learn_rows(body["rows"], body.get("total"))

    def run(self, duration_sec, concurrency, stop_event=None, on_sample=None, freshness_interval=1.0):
        """Drive the mix for *duration_sec* (0 = until *stop_event*) from
        *concurrency* threads; *on_sample(Sample)* sees every request."""
        self.discover()
        stop = stop_event or threading.Event()
        samples, freshness, lock = [], [], threading.Lock()

        def record(sample):
            with lock:
                samples.append(sample)
            if on_sample:
                on_sample(sample)

        with _client(self.base_url, self.token) as client:
            self._warm_up(client)
        started = time.monotonic()
        deadline = started + duration_sec if duration_sec else None

        def done():
            return stop.is_set() or (deadline is not None and time.monotonic() >= deadline)

        def worker(i):
            rng = random.Random(None if self._rng_seed is None else self._rng_seed + i)
            names, weights = list(WEIGHTS), list(WEIGHTS.values())
            with _client(self.base_url, self.token) as client:
                while not done():
                    call = probe_routes.build(rng.choices(names, weights)[0], self._ws_app, self.voc, rng)
                    if call is not None:
                        sample, body = self._send(client, call)
                        record(sample)
                        self._learn(call.route, body)

        def fresh_loop():
            with _client(self.base_url, self.token) as client:
                while not done():
                    sample, body = self._send(client, probe_routes.live_call(self._ws_app))
                    record(sample)
                    lag = freshness_lag(body.get("rows", []) if body else [])
                    if lag is not None:
                        with lock:
                            freshness.append(lag)
                    stop.wait(freshness_interval)

        with ThreadPoolExecutor(max_workers=concurrency + 1) as pool:
            futures = [pool.submit(worker, i) for i in range(concurrency)] + [pool.submit(fresh_loop)]
            for f in futures:
                f.result()
        return build_report(samples, freshness, time.monotonic() - started, routes=ROUTES)


def freshness_lag(rows, now=None):
    """Seconds since the freshest ``probe_ts`` among running *rows*, or None."""
    stamps = [
        (r.get("metrics") or {}).get("probe_ts") for r in rows if r.get("status") == "running"
    ]
    stamps = [s for s in stamps if isinstance(s, (int, float))]
    return max(0.0, (now or time.time()) - max(stamps)) if stamps else None


def fetch_all_rows(base_url, ws, app, token=None, page_size=MAX_PAGE, archived=False, query=None):
    """Every row of the app's leaderboard (or those matching *query*), paged in
    storage order (new runs append at the end, so a concurrent writer can't
    shift earlier pages); de-duplicated by verstr."""
    rows, seen, offset = [], set(), 0
    params = {"limit": min(page_size, MAX_PAGE)}
    if archived:
        params["archived"] = 1
    if query:
        params["q"] = query
    with _client(base_url, token) as client:
        while True:
            body = client.get(f"{app_path(ws, app)}/experiments",
                              params=dict(params, offset=offset)).raise_for_status().json()
            for row in body["rows"]:
                if row["verstr"] not in seen:
                    seen.add(row["verstr"])
                    rows.append(row)
            offset += len(body["rows"])
            if not body["rows"] or offset >= body["total"]:
                return rows


def status_counts(rows):
    """``{status: n}`` over *rows*."""
    return dict(Counter(r.get("status") for r in rows))


def by_name(rows):
    """``{run name: row}`` — the run identity the scenario/oracle use."""
    return {r["name"]: r for r in rows if r.get("name")}
