"""Playwright checks of the `vmn-exp ui` dashboard: first paint, scroll jank,
run-detail charts, query filtering, idle memory, status counts, console errors.

    with BrowserChecks("http://127.0.0.1:8265", "ws", "loadapp") as bc:
        results = bc.run_all(budget="smoke")
"""
import json
import time
from urllib.parse import parse_qs, quote, urlencode, urlparse

from uiload import browser_js as js

STATUSES = ("running", "stuck", "failed", "succeeded", "created")
TIMEOUT_MS = 30_000

_BASE = {"max_longtask_ms": 200, "chart_ms": 1500, "query_ms": 1000, "idle_growth_mb": 30}
BROWSER_BUDGETS = {
    "smoke": dict(_BASE, first_rows_ms=2000),
    "load": dict(_BASE, first_rows_ms=3000),
    "soak": dict(_BASE, first_rows_ms=3000),
}


def evaluate(results, profile):
    """Budget breaches in *results* (a run_all dict) as readable strings.
    *profile* is a BROWSER_BUDGETS key or a budget dict."""
    budget = BROWSER_BUDGETS[profile] if isinstance(profile, str) else profile
    problems = [
        f"{key}={results[key]:.0f} over budget {limit}"
        for key, limit in budget.items()
        if results.get(key) is not None and results[key] > limit
    ]
    if results.get("console_errors"):
        problems.append(f"console errors: {results['console_errors'][:5]}")
    return problems


def _ms_since(t0):
    return (time.perf_counter() - t0) * 1000


class BrowserChecks:
    """One headless chromium page on the dashboard of app *app* in workspace *ws*."""

    def __init__(self, base_url, ws, app, token=None, headless=True):
        self.base_url = base_url.rstrip("/")
        self.ws, self.app, self.token, self.headless = ws, app, token, headless
        app_tag = app.replace("/", "-")
        self.board_url = f"{self.base_url}/ws/{quote(ws)}/app/{quote(app_tag)}"
        self.api_url = f"{self.base_url}/api/v1/workspaces/{quote(ws)}/apps/{quote(app_tag)}"
        self._errors = []

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                headless=self.headless, args=["--enable-precise-memory-info"]
            )
        except Exception:
            self._pw.stop()
            raise
        context = self._browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_init_script(js.LONGTASK_INIT)
        if self.token:
            context.add_init_script(js.TOKEN_INIT % json.dumps(self.token))
        self.page = context.new_page()
        self.page.set_default_timeout(TIMEOUT_MS)
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda exc: self._errors.append(f"pageerror: {exc}"))
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def _on_console(self, msg):
        if msg.type == "error":
            self._errors.append(f"console: {msg.text}")

    def console_errors(self):
        return list(self._errors)

    # -- navigation ---------------------------------------------------------

    def _open_board(self, **params):
        url = self.board_url + (f"?{urlencode(params)}" if params else "")
        t0 = time.perf_counter()
        self.page.goto(url, wait_until="commit")
        return t0

    def _wait_total(self):
        """The filtered total the leaderboard subtitle shows, once loaded."""
        self.page.wait_for_function(js.PAGE_TOTAL_SHOWN)
        return self.page.evaluate(js.PAGE_TOTAL)

    def _api_rows(self, **params):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        resp = self.page.request.get(f"{self.api_url}/experiments?{urlencode(params)}", headers=headers)
        assert resp.ok, f"{resp.status} {resp.text()[:200]}"
        return resp.json()["rows"]

    def _verstr_of(self, run_name):
        rows = self._api_rows(q=f"name = {json.dumps(run_name)}", limit=1)
        if not rows:
            raise LookupError(f"no run named {run_name!r}")
        return rows[0]["verstr"]

    # -- checks -------------------------------------------------------------

    def leaderboard_first_rows_ms(self):
        t0 = self._open_board()
        self.page.wait_for_selector(js.ROW_SELECTOR)
        return _ms_since(t0)

    def scroll_jank(self, duration_sec=5):
        self._open_board()
        self.page.wait_for_selector(js.ROW_SELECTOR)
        out = self.page.evaluate(js.SCROLL, duration_sec * 1000)
        tasks = out["longtasks"]
        return {"longtasks_n": len(tasks), "max_longtask_ms": max(tasks, default=0.0),
                "rows_seen": out["rowsSeen"]}

    def run_detail_chart_ms(self, run_name):
        verstr = self._verstr_of(run_name)
        t0 = time.perf_counter()
        self.page.goto(f"{self.board_url}/run/{quote(verstr, safe='')}", wait_until="commit")
        # Charts mount lazily when scrolled into view; a wide run pushes them below the fold.
        self.page.locator(js.CHART_SELECTOR).first.scroll_into_view_if_needed()
        self.page.wait_for_function(js.CHART_PAINTED)
        return _ms_since(t0)

    def query_filter_ms(self, q):
        """(ms from typing *q* until the table shows its result, the UI's row count).
        The time includes the query box's 300ms debounce."""
        self._open_board()
        self.page.wait_for_selector(js.ROW_SELECTOR)

        def is_answer(resp):
            url = urlparse(resp.url)
            return url.path == urlparse(self.api_url).path + "/experiments" \
                and parse_qs(url.query).get("q") == [q]

        with self.page.expect_response(is_answer) as info:
            t0 = time.perf_counter()
            self.page.get_by_label("Filter query").fill(q)
        total = info.value.json()["total"]
        self.page.wait_for_function(js.PAGE_TOTAL_IS, arg=total)
        return _ms_since(t0), self.page.evaluate(js.PAGE_TOTAL)

    def status_pill_counts(self):
        """{"visible": pills per status in the rendered rows,
            "totals": per status, the filtered total the UI shows for ?status=<s>}."""
        self._open_board()
        self.page.wait_for_selector(js.ROW_SELECTOR)
        visible = {}
        for status in self.page.evaluate(js.VISIBLE_PILLS):
            visible[status] = visible.get(status, 0) + 1
        totals = {}
        for status in STATUSES:
            self._open_board(status=status)
            totals[status] = self._wait_total()
        return {"visible": visible, "totals": totals}

    def idle_memory_growth(self, duration_sec, interval_sec=1.0):
        """JS heap while the leaderboard sits with Live polling on."""
        self._open_board()
        self.page.wait_for_selector(js.ROW_SELECTOR)
        live = self.page.locator("button.live-toggle")
        if live.get_attribute("aria-pressed") != "true":
            live.click()
        heap = []
        end = time.monotonic() + duration_sec
        while True:
            heap.append(self.page.evaluate(js.HEAP_BYTES) or 0)
            if time.monotonic() >= end:
                break
            self.page.wait_for_timeout(min(interval_sec, end - time.monotonic()) * 1000)
        start_mb, end_mb = heap[0] / 2**20, heap[-1] / 2**20
        return {"start_mb": start_mb, "end_mb": end_mb, "growth_mb": end_mb - start_mb,
                "samples": len(heap)}

    def run_all(self, budget=None, run_name=None, query='status = "running"',
                scroll_sec=5, idle_sec=120):
        """Every metric in one dict; with *budget* (profile or dict) also "violations"."""
        results = {"first_rows_ms": self.leaderboard_first_rows_ms()}
        results.update(self.scroll_jank(scroll_sec))
        run_name = run_name or self._api_rows(sort="timestamp", limit=1)[0]["name"]
        results["chart_ms"] = self.run_detail_chart_ms(run_name)
        results["query_ms"], results["query_rows"] = self.query_filter_ms(query)
        results["status_counts"] = self.status_pill_counts()
        idle = self.idle_memory_growth(idle_sec)
        results.update({f"idle_{k}": v for k, v in idle.items()})
        results["console_errors"] = self.console_errors()
        if budget is not None:
            results["violations"] = evaluate(results, budget)
        return results
