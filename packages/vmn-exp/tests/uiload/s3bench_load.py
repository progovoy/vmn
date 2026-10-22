"""s3bench's client side: the requests a browser tab sends, timed.

* :func:`cold_series` — the Compare page's and an outer run's Charts→Curves
  ``POST .../series`` (with the row lookup the overlay sends beside it).
* :class:`BrowserLoad` — *clients* tabs on the Single runs board, each holding
  the ``events?scope=top`` SSE stream and revalidating its rows + facets (with
  their ETags) on every ``change`` (``useJobsBoard`` → ``useBoardLive``), plus
  hover prefetches of run detail and series; meanwhile a prober issues the
  board's filtered rows request (a new filter: no ETag) every few seconds.
"""
import json
import random
import threading
import time

import httpx

from uiload.probe import API, _ms_since, app_path
from uiload.probe_routes import OVERLAY_POINTS, PAGE_SIZE
from uiload.probe_stats import Sample, build_report

BOARD = "board_filter"
ROUTES = (BOARD, "tab_rows", "tab_facets", "hover_detail", "hover_series")
TIMEOUT = httpx.Timeout(300.0)


def board_params():
    """The Single runs board's rows request, in the web client's param order
    (api.ts ``fetchPage`` / ``setFilter``; flat, default ``idx`` sort)."""
    return [("offset", "0"), ("sort", "idx"), ("status", "succeeded"), ("top", "singles"),
            ("limit", str(PAGE_SIZE))]


def series_body(verstrs):
    return {"verstrs": verstrs, "keys": None, "max_points": OVERLAY_POINTS}


def _verstr_query(verstrs):
    return "verstr in (" + ", ".join(json.dumps(v) for v in verstrs) + ")"


def _timed(fn):
    t0 = time.perf_counter()
    r = fn()
    return r, round(_ms_since(t0), 1)


def _overlay(client, base, verstrs):
    """The overlay's two parallel reads; returns the series ms and points."""
    rows = threading.Thread(target=lambda: client.get(f"{base}/experiments", params={
        "offset": "0", "limit": str(len(verstrs)), "q": _verstr_query(verstrs)}))
    rows.start()
    r, ms = _timed(lambda: client.post(f"{base}/series", json=series_body(verstrs)))
    rows.join()
    r.raise_for_status()
    series = r.json()["series"]
    points = sum(len(pts) for run in series.values() for pts in run.values())
    return {"ms": ms, "runs": len(series), "points": points, "bytes": len(r.content)}


def cold_series(base_url, ws, app, stuck, outer, goal):
    """Compare of two stuck runs and an outer run's top 20: cold, then warm."""
    base = f"{API}{app_path(ws, app)}"
    out = {}
    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as c:
        pair = stuck[:2]
        out["compare_stuck_cold"] = _overlay(c, base, pair)
        out["compare_stuck_warm"] = _overlay(c, base, pair)
        r, ms = _timed(lambda: c.get(f"{base}/experiments", params={
            "offset": "0", "sort": goal, "scope": outer, "limit": "20"}))
        top = [row["verstr"] for row in r.raise_for_status().json()["rows"]]
        out["outer_top20_rows"] = {"ms": ms, "runs": len(top),
                                   "stuck": sum(v in set(stuck) for v in top)}
        out["outer_top20_cold"] = _overlay(c, base, top)
        out["outer_top20_warm"] = _overlay(c, base, top)
    return out


class BrowserLoad:
    def __init__(self, base_url, ws, app, clients, stuck, probe_every=3.0, hover_every=1.0):
        self.base_url, self.clients = base_url, clients
        self.base = f"{API}{app_path(ws, app)}"
        self.stuck, self.probe_every, self.hover_every = stuck, probe_every, hover_every
        self.samples, self.events, self.stream_errors = [], 0, 0
        self.rows = []
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def _record(self, route, fn, conditional=False):
        t0 = time.perf_counter()
        r, error = None, None
        try:
            r = fn()
        except httpx.HTTPError as e:
            error = repr(e)
        ok = r is not None
        s = Sample(route, _ms_since(t0), r.status_code if ok else None,
                   len(r.content) if ok else 0, conditional, error)
        with self.lock:
            self.samples.append(s)
        return r

    def _revalidate(self, client, etags, route, path, params=None, keep_rows=False):
        key = (path, str(params))
        headers = {"If-None-Match": etags[key]} if key in etags else {}
        r = self._record(route, lambda: client.get(path, params=params, headers=headers),
                         bool(headers))
        if r is not None and r.status_code == 200:
            if r.headers.get("etag"):
                etags[key] = r.headers["etag"]
            if keep_rows:
                with self.lock:
                    self.rows = [row["verstr"] for row in r.json()["rows"]]

    def _tab(self, n):
        """One tab: first paint, then one revalidation per ``change`` event
        (a change arriving meanwhile folds into the next one, like
        ``useSerialized``)."""
        etags = {}
        with httpx.Client(base_url=self.base_url, timeout=TIMEOUT) as c:
            # One tab feeds the hover pool: parsing every tab's rows would
            # hold the GIL while other threads stop their timers.
            refresh = lambda: (self._revalidate(c, etags, "tab_rows", f"{self.base}/experiments",  # noqa: E731
                                                board_params(), keep_rows=n == 0),
                               self._revalidate(c, etags, "tab_facets", f"{self.base}/experiments-facets"))
            refresh()
            pending = threading.Event()
            worker = threading.Thread(target=self._refresher, args=(pending, refresh), daemon=True)
            worker.start()
            while not self.stop.is_set():
                try:
                    self._follow(c, pending)
                except httpx.HTTPError:
                    with self.lock:
                        self.stream_errors += 1
                    self.stop.wait(3)  # EventSource retry

    def _refresher(self, pending, refresh):
        while not self.stop.is_set():
            if pending.wait(0.2):
                pending.clear()
                refresh()

    def _follow(self, client, pending):
        with client.stream("GET", f"{self.base}/events", params={"scope": "top"},
                           timeout=httpx.Timeout(10.0, read=60.0)) as r:
            event = None
            for line in r.iter_lines():
                if self.stop.is_set():
                    return
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event == "change":
                    with self.lock:
                        self.events += 1
                    pending.set()
                elif not line:
                    event = None

    def _prober(self):
        with httpx.Client(base_url=self.base_url, timeout=TIMEOUT) as c:
            while not self.stop.wait(self.probe_every):
                self._record(BOARD, lambda: c.get(f"{self.base}/experiments", params=board_params()))

    def _hover(self, seed):
        rng = random.Random(seed)
        with httpx.Client(base_url=self.base_url, timeout=TIMEOUT) as c:
            while not self.stop.wait(self.hover_every):
                with self.lock:
                    pool = self.rows or self.stuck
                v = rng.choice(pool + self.stuck[:20])
                self._record("hover_detail", lambda: c.get(f"{self.base}/experiments/{v}"))
                if rng.random() < 0.3:
                    pair = rng.sample(pool + self.stuck, 2)
                    self._record("hover_series", lambda: c.post(f"{self.base}/series",
                                                                json=series_body(pair)))

    def run(self, duration_sec):
        threads = [threading.Thread(target=self._tab, args=(n,), daemon=True)
                   for n in range(self.clients)]
        threads += [threading.Thread(target=self._prober, daemon=True)]
        threads += [threading.Thread(target=self._hover, args=(n,), daemon=True)
                    for n in range(max(1, self.clients // 2))]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        self.stop.wait(duration_sec)
        self.stop.set()
        elapsed = time.monotonic() - t0
        with self.lock:
            samples, events = list(self.samples), self.events
        report = build_report(samples, [], elapsed, ROUTES).to_dict()
        minutes = elapsed / 60
        report["sse"] = {"change_events": events,
                         "per_tab_per_min": round(events / max(1, self.clients) / minutes, 2),
                         "stream_errors": self.stream_errors}
        return report
