"""Measure a seeded fgm store (plan 28 B0, :mod:`uiload.seed_fgm`) against a
server: once its index holds every run, each route in :data:`ROUTES` is
requested ``profile.probe_requests`` times (no ``If-None-Match``), the first
request timed apart (``first_ms``: the first after a refresh).

    measure(base_url, ws, app, profile, expected=n) -> result   # slo.fgm_evaluate

* ``status``: ``experiments-status``;
* ``summary`` / ``summary_split``: the live launch's summary, without and
  with ``?split=tags.kind``;
* ``board_kind``: the live launch's runs grouped by ``tags.kind``;
* ``board_dates``: the ended launch's unstable runs grouped by trade date;
* ``board_app``: the app's board grouped by parent, on ``value``;
* ``waiting``: P1's ``status = "created" and timestamp < ago(...)``, each
  request a minute further back (``ago("61m")``, ``ago("62m")``, ...): the
  server pins ``ago()`` to the minute and keys its caches on the pinned text,
  and ``status`` already built the 1 h order (the seeded ``waiting`` attention
  query), so every timed request pays the rebuild a minute rollover causes.

``waiting_cold_ms`` times one ``ago("59m")`` count first, right after the
index is ready: the first ``ago()`` order the server builds. Not the seeded
``ago("1h")`` itself: waiting for the index polls ``experiments-status``,
whose attention count already built that order.

The result also carries the status's ``attention`` counts and the summary's
default ``split``: the seeded store settings (:data:`uiload.seed_fgm.SETTINGS`)
read back through A0.

    python packages/vmn-exp/tests/uiload/probe_fgm.py /tmp/fgm   # serves it in-process
"""
import argparse
import json
import os
import sys
import tempfile
import time
from urllib.parse import quote

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uiload import fgm_tree, seed_fgm, slo
from uiload.inproc_server import serve_root
from uiload.probe import _client, _ms_since, app_path, wait_indexed
from uiload.probe_stats import _summary

ROUTES = ("status", "summary", "summary_split", "board_kind", "board_dates", "board_app",
          "waiting")
INDEX_TIMEOUT_SEC = 6 * 3600
WAITING = seed_fgm.WAITING


def cold_waiting(ws_app):
    """The first ``ago()`` board request, a minute no status poll pinned."""
    return f"{ws_app}/experiments", _waiting(-2)


def _waiting(i):
    return {"q": f'status = "created" and timestamp < ago("{61 + i}m")', "limit": 1}


def _requests(ws_app, live, ended):
    def run(verstr, tail=""):
        return f"{ws_app}/experiments/{quote(verstr, safe='')}{tail}"

    board = f"{ws_app}/experiments"
    return {
        "status": lambda i: (f"{ws_app}/experiments-status", {}),
        "summary": lambda i: (run(live, "/summary"), {}),
        "summary_split": lambda i: (run(live, "/summary"), {"split": "tags.kind"}),
        "board_kind": lambda i: (board, {"group": "tags.kind", "scope": live, "limit": 50}),
        "board_dates": lambda i: (board, {"group": "tags.trade_date", "scope": ended,
                                          "q": 'tags.health = "unstable"', "limit": 50}),
        "board_app": lambda i: (board, {"group": "parent", "sort": "value", "limit": 50}),
        "waiting": lambda i: (board, _waiting(i)),
    }


def _launches(client, ws_app):
    rows = client.get(f"{ws_app}/experiments", params={"q": 'tags.kind = "launch"',
                                                       "limit": 1000}).raise_for_status()
    by_status = {}
    for row in rows.json()["rows"]:
        by_status.setdefault(row["status"], row["verstr"])
    return by_status["running"], by_status["succeeded"]


def _timed(client, path, params):
    started = time.perf_counter()
    resp = client.get(path, params=params)
    return _ms_since(started), resp


def _get(client, request):
    path, params = request
    return client.get(path, params=params).raise_for_status().json()


def measure(base_url, ws, app, profile, expected, token=None):
    """The result dict :func:`uiload.slo.fgm_violations` reads."""
    ws_app = app_path(ws, app)
    index_sec, indexed = wait_indexed(base_url, ws, app, expected, token, INDEX_TIMEOUT_SEC)
    with _client(base_url, token) as client:
        cold_ms, resp = _timed(client, *cold_waiting(ws_app))
        live, ended = _launches(client, ws_app)
        requests = _requests(ws_app, live, ended)
        routes, errors = {}, int(resp.status_code != 200)
        for route, request in requests.items():
            times = []
            for i in range(profile.probe_requests):
                ms, resp = _timed(client, *request(i))
                times.append(ms)
                errors += resp.status_code != 200
            routes[route] = dict(_summary(times), first_ms=times[0])
        split = _get(client, requests["summary_split"](0))
        default_split = _get(client, requests["summary"](0)).get("split")
        status = _get(client, requests["status"](0))
    return {"routes": routes, "errors": errors, "status_total": indexed["total"],
            "index_sec": index_sec, "live": live, "ended": ended, "kinds": len(split["by"]),
            "attention": {e["key"]: e["count"] for e in status.get("attention", [])},
            "default_split": default_split, "waiting_cold_ms": cold_ms}


def main(argv=None):
    """Serve a root seeded by ``seed_fgm.py`` in-process, measure it, print the
    result and its budget breaches; exit 1 on any."""
    p = argparse.ArgumentParser(description=main.__doc__.split(",")[0])
    p.add_argument("root")
    p.add_argument("--data-dir", default=None, help="UI data dir (default a new temp dir)")
    a = p.parse_args(argv)
    with open(os.path.join(a.root, seed_fgm.MANIFEST)) as f:
        manifest = json.load(f)
    profile = fgm_tree.get_profile(manifest["profile"])
    data_dir = a.data_dir or tempfile.mkdtemp(prefix="uiload-ui-")
    started = time.monotonic()
    with serve_root(a.root, data_dir, "ws") as (url, ws):
        result = measure(url, ws, manifest["app"], profile, manifest["total"])
    result["seconds"] = round(time.monotonic() - started, 1)
    breaches = slo.fgm_evaluate(result, profile.name)
    print(json.dumps(dict(result, violations=breaches), indent=2))
    sys.exit(1 if breaches else 0)


if __name__ == "__main__":
    main()
