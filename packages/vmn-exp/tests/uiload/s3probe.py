#!/usr/bin/env python3
"""Time a real store's cold start: ``vmn-exp ui --read-only`` over it.

Starts ``vmn-exp ui --store <uri> --read-only`` with an empty cache dir (a cold
index, as after a fresh deploy on a new host), then, until the index has
loaded, asks for the Outer runs board (``top=jobs``) and a Compare of
``--compare`` runs back to back, printing each answer's latency and the
index's progress as it goes. Nothing is written to the store.

    python packages/vmn-exp/tests/uiload/s3probe.py --store s3://bucket/prefix \\
        --app fastglobalmacro --compare <verstr> <verstr> <verstr> --out probe.json

Uses the installed ``vmn-exp`` unless ``--src <checkout>`` names one; AWS
credentials come from the usual environment / profile.
"""
import argparse
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import httpx  # noqa: E402

from uiload.probe import API, app_path  # noqa: E402
from uiload.s3bench_coldload import ColdLoadProbe  # noqa: E402
from uiload.ui_server import INDEX_TIMEOUT_SEC, UIServer  # noqa: E402
from uiload.worker import with_src_pythonpath  # noqa: E402

PROGRESS_EVERY_SEC = 30


class ReadOnlyStoreUI(UIServer):
    """``vmn-exp ui --store <uri> --read-only`` with its own (empty) cache dir."""

    def __init__(self, store_uri, src, run_dir):
        super().__init__(None, run_dir, min_stale_sec=60)
        self.store_uri, self.src = store_uri, src

    def _env(self):
        env = dict(os.environ, VMN_EXP_CACHE_DIR=os.path.join(self.run_dir, "cache"))
        return with_src_pythonpath(env, os.path.abspath(self.src)) if self.src else env

    def _source_args(self):
        return ["--store", self.store_uri, "--read-only"]


def wait_loaded(base, probe):
    """Seconds until ``experiments-status`` stops reporting ``indexing``."""
    t0 = last = time.monotonic()
    with httpx.Client(timeout=60) as client:
        while time.monotonic() - t0 < INDEX_TIMEOUT_SEC:
            try:
                body = client.get(f"{base}/experiments-status").json()
            except (httpx.HTTPError, ValueError):
                body = {}
            if body.get("total") and "indexing" not in body:
                return round(time.monotonic() - t0, 1), body
            if time.monotonic() - last >= PROGRESS_EVERY_SEC:
                last = time.monotonic()
                sample = probe.samples[-1] if probe.samples else {}
                print(f"t={last - t0:.0f}s indexing={body.get('indexing')} last outer-runs "
                      f"{sample.get('ms')} ms, compare {sample.get('compare_ms')} ms", flush=True)
            time.sleep(2)
    raise TimeoutError(f"index not loaded after {INDEX_TIMEOUT_SEC}s")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--store", required=True, help="store URI, e.g. s3://bucket/prefix")
    p.add_argument("--app", required=True)
    p.add_argument("--compare", nargs="*", default=[], metavar="VERSTR",
                   help="runs to compare while the index loads (e.g. 3 stuck runs)")
    p.add_argument("--src", help="checkout to run vmn-exp from (default: the installed one)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    run_dir = tempfile.mkdtemp(prefix="s3probe-")
    print(f"run dir {run_dir} (ui.log there)", flush=True)
    ui = ReadOnlyStoreUI(args.store, args.src, run_dir).start()
    try:
        ws = httpx.get(f"{ui.base_url}{API}/workspaces", timeout=60).json()[0]["name"]
        base = f"{ui.base_url}{API}{app_path(ws, args.app)}"
        probe = ColdLoadProbe(ui.base_url, ws, args.app, args.compare).start()
        load_sec, status = wait_loaded(base, probe)
        cold = probe.stop()
    finally:
        ui.stop()
    report = {"index_load_sec": load_sec, "status": status, "cold_jobs": cold,
              "config": vars(args)}
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"index loaded in {load_sec}s; first outer-runs answer at "
          f"{cold['first_jobs_answer_sec']}s; slowest outer-runs {cold['max_ms']} ms")
    compares = [s["compare_ms"] for s in cold["samples"] if s["compare_ms"] is not None]
    if compares:
        print(f"compare: first {compares[0]} ms, slowest {max(compares)} ms, last {compares[-1]} ms")
    print(f"full samples in {args.out}")


if __name__ == "__main__":
    main()
