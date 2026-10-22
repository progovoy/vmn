"""s3bench's cold-load probe: the Outer runs board while a store's index loads.

A browser opening the experiments page right after a restart asks for the
top-level outer runs (``top=jobs``) while the index is still loading. The probe
asks the same, back to back, from the UI's start until the index is loaded,
and records each answer's latency, row count and the index progress then.
"""
import threading
import time

import httpx

from uiload.probe import API, app_path

JOBS_QUERY = {"offset": 0, "sort": "idx", "top": "jobs", "limit": 200}
REQUEST_TIMEOUT_SEC = 900


def _rows(body):
    return body.get("rows", body) if isinstance(body, dict) else body


def _progress(client, base):
    try:
        status = client.get(f"{base}/experiments-status", timeout=30).json()
    except (httpx.HTTPError, ValueError):
        return None
    indexing = status.get("indexing")
    return indexing["loaded"] if indexing else status.get("total")


class ColdLoadProbe:
    """Times ``experiments?top=jobs`` until :meth:`stop`."""

    def __init__(self, base_url, ws, app, compare=()):
        self.base = f"{base_url}{API}{app_path(ws, app)}"
        self.compare = list(compare)
        self.samples = []
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(REQUEST_TIMEOUT_SEC)
        return self.report()

    def _loop(self):
        with httpx.Client(timeout=REQUEST_TIMEOUT_SEC) as client:
            while not self._stop.is_set():
                self._sample(client)
                self._stop.wait(1)

    def _sample(self, client):
        sent = time.monotonic()
        try:
            resp = client.get(f"{self.base}/experiments", params=JOBS_QUERY)
            rows = len(_rows(resp.json())) if resp.status_code == 200 else None
            code = resp.status_code
        except (httpx.HTTPError, ValueError) as e:
            rows, code = None, type(e).__name__
        done = time.monotonic()
        self.samples.append({
            "at_sec": round(sent - self._t0, 1), "ms": round((done - sent) * 1000),
            "status": code, "rows": rows, "compare_ms": self._compare_ms(client),
            "indexed": _progress(client, self.base),
        })

    def _compare_ms(self, client):
        """A Compare of the stuck runs: their series, as the Curves tab asks."""
        if not self.compare:
            return None
        sent = time.monotonic()
        try:
            client.post(f"{self.base}/series", json={
                "verstrs": self.compare, "keys": None, "max_points": 1000})
        except httpx.HTTPError:
            return None
        return round((time.monotonic() - sent) * 1000)

    def report(self):
        answered = [s for s in self.samples if s["rows"]]
        first = answered[0] if answered else None
        return {
            "first_jobs_answer_sec": first and round(first["at_sec"] + first["ms"] / 1000, 1),
            "first_answer_indexed": first and first["indexed"],
            "max_ms": max((s["ms"] for s in self.samples), default=None),
            "samples": self.samples,
        }
