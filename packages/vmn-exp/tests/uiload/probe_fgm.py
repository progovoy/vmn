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
* ``waiting``: ``status = "created" and timestamp < "<an hour ago>"``, the
  literal a minute later each time (what P1's ``ago("1h")`` rebuilds).

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
from uiload import fgm_records, fgm_tree, seed_fgm, slo
from uiload.inproc_server import serve_root
from uiload.probe import _client, _ms_since, app_path, wait_indexed
from uiload.probe_stats import _summary

ROUTES = ("status", "summary", "summary_split", "board_kind", "board_dates", "board_app",
          "waiting")
INDEX_TIMEOUT_SEC = 6 * 3600


def _requests(ws_app, live, ended, now):
    def run(verstr, tail=""):
        return f"{ws_app}/experiments/{quote(verstr, safe='')}{tail}"

    def waiting(i):
        since = fgm_records.iso(now - 3600 + 60 * i)
        return {"q": f'status = "created" and timestamp < "{since}"', "limit": 1}

    board = f"{ws_app}/experiments"
    return {
        "status": lambda i: (f"{ws_app}/experiments-status", {}),
        "summary": lambda i: (run(live, "/summary"), {}),
        "summary_split": lambda i: (run(live, "/summary"), {"split": "tags.kind"}),
        "board_kind": lambda i: (board, {"group": "tags.kind", "scope": live, "limit": 50}),
        "board_dates": lambda i: (board, {"group": "tags.trade_date", "scope": ended,
                                          "q": 'tags.health = "unstable"', "limit": 50}),
        "board_app": lambda i: (board, {"group": "parent", "sort": "value", "limit": 50}),
        "waiting": lambda i: (board, waiting(i)),
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


def measure(base_url, ws, app, profile, expected, token=None, now=None):
    """The result dict :func:`uiload.slo.fgm_violations` reads."""
    ws_app, now = app_path(ws, app), time.time() if now is None else now
    index_sec, indexed = wait_indexed(base_url, ws, app, expected, token, INDEX_TIMEOUT_SEC)
    with _client(base_url, token) as client:
        live, ended = _launches(client, ws_app)
        requests = _requests(ws_app, live, ended, now)
        routes, errors = {}, 0
        for route, request in requests.items():
            times = []
            for i in range(profile.probe_requests):
                ms, resp = _timed(client, *request(i))
                times.append(ms)
                errors += resp.status_code != 200
            routes[route] = dict(_summary(times), first_ms=times[0])
        path, params = requests["summary_split"](0)
        split = client.get(path, params=params).raise_for_status().json()
    return {"routes": routes, "errors": errors, "status_total": indexed["total"],
            "index_sec": index_sec, "live": live, "ended": ended, "kinds": len(split["by"])}


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
        result = measure(url, ws, manifest["app"], profile, manifest["total"],
                         now=manifest["now"])
    result["seconds"] = round(time.monotonic() - started, 1)
    breaches = slo.fgm_evaluate(result, profile.name)
    print(json.dumps(dict(result, violations=breaches), indent=2))
    sys.exit(1 if breaches else 0)


if __name__ == "__main__":
    main()
