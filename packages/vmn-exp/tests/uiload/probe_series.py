"""Measure a seeded ``bigseries`` profile (plan 12 §10 4b) against a server.

    measure(base_url, ws, app, profile) -> result   # slo.series_evaluate(result, name)

* ``series``: one big run's key at ``profile.series_points`` (``POST .../series``);
* ``zoom``: the same over a random 1% step window (``step_min``/``step_max``,
  plan 12 §7; a server without range params answers the full range);
* ``first_paint_bytes``: the run page's detail fetch (wire bytes), worst of a
  big and the wide run;
* ``overlay_ms``: one key of every overlay run, in ``MAX_RUNS``-run requests
  sent in parallel, wall clock for the lot.
"""
import argparse
import json
import os
import random
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uiload import scenario, slo
from uiload.inproc_server import serve_root
from uiload.probe import _client, _ms_since, app_path, fetch_all_rows
from uiload.probe_routes import OVERLAY_POINTS
from uiload.probe_stats import _summary
from uiload.seed_series import metric_names
from vmn_exp.ui.routes_series import MAX_RUNS

ZOOM_FRACTION = 0.01
OVERLAY_WORKERS = 8


class _Session:
    def __init__(self, client, ws_app):
        self.client, self.ws_app = client, ws_app
        self.errors = 0
        self.points_max = 0

    def series(self, verstrs, keys, max_points, **window):
        body = dict({"verstrs": verstrs, "keys": keys, "max_points": max_points}, **window)
        started = time.perf_counter()
        resp = self.client.post(f"{self.ws_app}/series", json=body)
        ms = _ms_since(started)
        if resp.status_code != 200:
            self.errors += 1
            return ms
        for per_run in resp.json()["series"].values():
            for points in per_run.values():
                self.points_max = max(self.points_max, len(points))
        return ms

    def detail_bytes(self, verstr):
        resp = self.client.get(f"{self.ws_app}/experiments/{quote(verstr, safe='')}")
        if resp.status_code != 200:
            self.errors += 1
        return resp.num_bytes_downloaded


def _by_group(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row["name"].split("-", 1)[0], []).append(row["verstr"])
    return groups


def _timed_series(session, rng, profile, verstrs, zoom):
    keys = metric_names(profile.big_keys)
    out = []
    for _ in range(profile.probe_requests):
        window = {}
        if zoom:
            width = max(2, int(profile.big_steps * ZOOM_FRACTION))
            lo = rng.randrange(max(1, profile.big_steps - width))
            window = {"step_min": lo, "step_max": lo + width}
        out.append(session.series([rng.choice(verstrs)], [rng.choice(keys)],
                                  profile.series_points, **window))
    return out


def _overlay_ms(session, verstrs):
    chunks = [verstrs[i:i + MAX_RUNS] for i in range(0, len(verstrs), MAX_RUNS)]
    started = time.perf_counter()
    with ThreadPoolExecutor(OVERLAY_WORKERS) as pool:
        list(pool.map(lambda c: session.series(c, ["loss"], OVERLAY_POINTS), chunks))
    return _ms_since(started)


def measure(base_url, ws, app, profile, token=None, seed=0):
    """The result dict :func:`uiload.slo.series_violations` reads."""
    groups = _by_group(fetch_all_rows(base_url, ws, app, token=token))
    rng = random.Random(seed)
    with _client(base_url, token) as client:
        session = _Session(client, app_path(ws, app))
        session.series(groups["big"][:1], ["loss"], profile.series_points)  # warm the index
        series = _timed_series(session, rng, profile, groups["big"], zoom=False)
        zoom = _timed_series(session, rng, profile, groups["big"], zoom=True)
        first_paint = max(session.detail_bytes(v) for v in groups["big"][:1] + groups["wide"][:1])
        overlay = _overlay_ms(session, groups["overlay"])
    return {"series": _summary(series), "zoom": _summary(zoom),
            "first_paint_bytes": first_paint, "overlay_ms": overlay,
            "overlay_runs": len(groups["overlay"]), "series_points_max": session.points_max,
            "errors": session.errors}


def main(argv=None):
    """Serve a root seeded by ``seed_series.py`` in-process, measure it, print
    the result and its SLO breaches; exit 1 on any."""
    p = argparse.ArgumentParser(description=main.__doc__.split(",")[0])
    p.add_argument("root")
    p.add_argument("--profile", default="bigseries", choices=sorted(scenario.SERIES_PROFILES))
    p.add_argument("--app", default="loadapp")
    p.add_argument("--data-dir", default=None, help="UI data dir (default a new temp dir)")
    a = p.parse_args(argv)
    profile = scenario.get_series_profile(a.profile)
    with serve_root(a.root, a.data_dir or tempfile.mkdtemp(prefix="uiload-ui-"), "ws") as (url, ws):
        result = measure(url, ws, a.app, profile)
    breaches = slo.series_evaluate(result, a.profile)
    print(json.dumps(dict(result, violations=breaches), indent=2))
    sys.exit(1 if breaches else 0)


if __name__ == "__main__":
    main()
