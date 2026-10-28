"""s3bench: a production-shaped S3 store served by a real ``vmn-exp ui``, timed.

    python packages/vmn-exp/tests/uiload/s3bench.py --src <checkout> \\
        [--runs 20000] [--stuck 740] [--segments 300] [--latency-ms 30] \\
        [--clients 4] [--duration 60] [--data <seed dir>] --out report.json

Seeds the store once (:mod:`uiload.s3bench_seed`; reused from ``--data``
when its manifest matches the sizes, so a baseline and a fix read identical
objects), serves it from a moto server with per-request latency
(:mod:`uiload.s3bench_moto`), and runs ``vmn-exp ui --store s3://...`` from
``--src``'s package sources with a fresh per-host cache (a cold start). Then
times the cold index load, the Compare / outer-run Curves series and the
Single runs board under browser-like load (:mod:`uiload.s3bench_load`), and
counts the S3 requests of each phase.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uiload.worker import SRC_DIRS, src_dirs, with_src_pythonpath

sys.path[1:1] = [d for d in SRC_DIRS if d not in sys.path]

import httpx  # noqa: E402

from uiload import s3bench_load, s3bench_seed  # noqa: E402
from uiload.s3bench_coldload import ColdLoadProbe  # noqa: E402
from uiload.probe import API, wait_indexed  # noqa: E402
from uiload.ui_server import UIServer, free_port  # noqa: E402

BUCKET, ROOT = "bench", "vmn-exp"
HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_TIMEOUT_SEC = 7200


def check_src(src):
    missing = [d for d in src_dirs(src) if not os.path.isdir(d)]
    if missing:
        raise SystemExit(f"--src {src}: no {missing[0]}")


def aws_env(env):
    return dict(env, AWS_ACCESS_KEY_ID="bench", AWS_SECRET_ACCESS_KEY="bench",
                AWS_DEFAULT_REGION="us-east-1", AWS_EC2_METADATA_DISABLED="true")


class StoreUIServer(UIServer):
    """``vmn-exp ui --store <uri>`` from *src*, with its own cache dir."""

    def __init__(self, store_uri, src, run_dir):
        super().__init__(None, run_dir, min_stale_sec=60)
        self.store_uri, self.src = store_uri, os.path.abspath(src)

    def _env(self):
        env = dict(os.environ, VMN_EXP_CACHE_DIR=os.path.join(self.run_dir, "cache"))
        env.pop("PYTHONPATH", None)
        return aws_env(with_src_pythonpath(env, self.src))

    def _source_args(self):
        return ["--store", self.store_uri]


def start_moto(data, latency_ms, run_dir, fast=False):
    """The fake S3 serving *data*: moto, or with *fast* :mod:`uiload.s3bench_fast`
    (for throughput: moto saturates at ~800 requests a second)."""
    port = free_port()
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.dirname(HERE)] + SRC_DIRS))
    script = "s3bench_fast.py" if fast else "s3bench_moto.py"
    cmd = [sys.executable, os.path.join(HERE, script), "--port", str(port),
           "--latency-ms", str(latency_ms), "--data", data, "--bucket", BUCKET, "--root", ROOT]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                            stderr=open(os.path.join(run_dir, "moto.log"), "ab"), text=True)
    line = proc.stdout.readline()
    if not line.startswith("READY"):
        raise RuntimeError(f"moto server failed; see {run_dir}/moto.log")
    return proc, f"http://127.0.0.1:{port}", float(line.split()[3])


def s3_requests(endpoint):
    return httpx.get(f"{endpoint}/__stats", timeout=10).json()


def _deltas(marks):
    """The S3 requests of each phase, from ``[(phase, stats after it)]``."""
    return {phase: {k: round(v - before.get(k, 0), 2) for k, v in after.items()}
            for (_, before), (phase, after) in zip(marks, marks[1:])}


def seed_data(args):
    params = {"runs": args.runs, "stuck": args.stuck, "segments": args.segments, "seed": args.seed}
    data = args.data or os.path.join(tempfile.gettempdir(),
                                     "s3bench-{runs}-{stuck}-{segments}-{seed}".format(**params))
    manifest = s3bench_seed.load_manifest(data, params)
    if manifest:
        return data, manifest, 0.0
    if os.path.isdir(data) and os.listdir(data):
        raise SystemExit(f"--data {data} holds another seed; give an empty or matching dir")
    t0 = time.monotonic()
    manifest = s3bench_seed.seed(data, params, time.time())
    return data, manifest, round(time.monotonic() - t0, 1)


def measure(args, manifest, ui, endpoint):
    ws = httpx.get(f"{ui.base_url}{API}/workspaces", timeout=60).json()[0]["name"]
    app = manifest["app"]
    report = {}
    marks = [("start", s3_requests(endpoint))]
    cold = ColdLoadProbe(ui.base_url, ws, app, manifest["stuck"][:3]).start()
    report["index_load_sec"], report["status"] = wait_indexed(ui.base_url, ws, app, args.runs, timeout=INDEX_TIMEOUT_SEC)
    report["cold_jobs"] = cold.stop()
    marks.append(("index", s3_requests(endpoint)))
    if args.cold_only:
        report["s3_requests"] = _deltas(marks)
        return report
    outer = max(manifest["outers"], key=lambda o: o["runs"])["verstr"]
    report["series"] = s3bench_load.cold_series(ui.base_url, ws, app, manifest["stuck"], outer,
                                                manifest["goal"][0])
    marks.append(("series", s3_requests(endpoint)))
    load = s3bench_load.BrowserLoad(ui.base_url, ws, app, args.clients, manifest["stuck"])
    report["board"] = load.run(args.duration)
    marks.append(("board", s3_requests(endpoint)))
    report["s3_requests"] = _deltas(marks)
    return report


def _ms(v):
    return "-" if v is None else f"{v:.0f}"


def print_cold(cold):
    print(f"cold load: first outer-runs answer at {cold['first_jobs_answer_sec']}s "
          f"(indexed {cold['first_answer_indexed']}), slowest {_ms(cold['max_ms'])} ms")
    for s in cold["samples"]:
        print(f"  t={s['at_sec']:>7}s {s['ms']:>7} ms  rows={s['rows']}  compare={s['compare_ms']} ms  indexed={s['indexed']}")


def print_table(report):
    print(f"index load: {report['index_load_sec']}s   status: {report['status'].get('counts')}")
    print_cold(report["cold_jobs"])
    if "series" not in report:
        return
    for name, s in report["series"].items():
        extra = f" runs={s.get('runs')} points={s.get('points', '-')}"
        print(f"  {name:22s} {s['ms']:>9.0f} ms {extra}")
    board = report["board"]
    print(f"{'route':16s} {'n':>5s} {'p50':>7s} {'p95':>7s} {'max':>7s} {'304':>5s} {'err':>4s}")
    for name, r in board["routes"].items():
        print(f"{name:16s} {r['count']:>5d} {_ms(r['p50']):>7s} {_ms(r['p95']):>7s} "
              f"{_ms(r['max']):>7s} {r['not_modified']:>5d} {r['errors']:>4d}")
    rate = board["rate_304"]
    print(f"SSE change events: {board['sse']['change_events']} "
          f"({board['sse']['per_tab_per_min']}/tab/min), 304 rate "
          f"{'-' if rate is None else f'{rate:.0%}'}")
    print("S3 requests per phase:", json.dumps(report["s3_requests"]))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", required=True, help="checkout whose packages/*/src the UI runs")
    p.add_argument("--runs", type=int, default=20_000)
    p.add_argument("--stuck", type=int, default=740)
    p.add_argument("--segments", type=int, default=300)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--latency-ms", type=float, default=30)
    p.add_argument("--clients", type=int, default=4)
    p.add_argument("--duration", type=float, default=60)
    p.add_argument("--data", help="seed dir (reused when it matches the sizes)")
    p.add_argument("--run-dir", help="logs + the UI's data/cache (default: a new temp dir)")
    p.add_argument("--out", required=True)
    p.add_argument("--cold-only", action="store_true",
                   help="stop once the index is loaded: only the cold-load probe")
    args = p.parse_args(argv)
    run_dir = args.run_dir or tempfile.mkdtemp(prefix="s3bench-run-")
    os.makedirs(run_dir, exist_ok=True)
    data, manifest, seed_sec = seed_data(args)
    print(f"data {data} ({manifest['objects']} objects, seeded in {seed_sec}s); run dir {run_dir}",
          flush=True)
    check_src(args.src)
    moto, endpoint, load_sec = start_moto(data, args.latency_ms, run_dir)
    ui = None
    try:
        print(f"moto {endpoint}: loaded in {load_sec}s", flush=True)
        ui = StoreUIServer(f"s3://{BUCKET}/{ROOT}?endpoint_url={endpoint}", args.src, run_dir).start()
        report = measure(args, manifest, ui, endpoint)
    finally:
        if ui:
            ui.stop()
        moto.terminate()
    report = dict(report, config=dict(vars(args), data=data, run_dir=run_dir,
                                      objects=manifest["objects"], seed_sec=seed_sec, moto_load_sec=load_sec))
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, default=str)
    print_table(report)


if __name__ == "__main__":
    main()
