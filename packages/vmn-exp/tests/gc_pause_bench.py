"""How long the cyclic collector stops a ``vmn-exp ui`` server holding N runs
(plan 28 Appendix A row 6). Not a pytest test.

Each case runs in a fresh process on a :mod:`scale_store` store of N runs:

- *cold*: the index loads the store as a remote one (a chunk at a time, the
  collector on across its reads, as on S3) while a request thread pages the
  board of each published snapshot; then the board is warmed the way the
  refresher does once the load is over;
- *warm*: a restart on the index file the cold case left, the board warmed.

Every collection is timed with the diag dump's ``gc.callbacks`` hook
(:class:`~vmn_exp.ui.diag.gc_pauses.GcPauses`); after each case the bench
counts the collected objects, times ``gc.collect()`` and, from the cold
case, the steady state: a minute's worth of board requests and no-change
refreshes.

    python packages/vmn-exp/tests/gc_pause_bench.py --runs 100000 [--python /path/to/python3.14t ...]
"""
import argparse
import gc
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SRC = [os.path.join(REPO, "packages", d, "src") for d in ("vmn", "vmn-exp-sdk", "vmn-exp")]
SCHEMA = {"loss": {"goal": "min", "primary": True}}
QUERIES = (None, 'status = "failed"', "metrics.loss < 0.5", 'params.opt = "adam"')


def _ms(sec):
    return round(sec * 1000, 1)


def _timed(fn):
    started = time.perf_counter()
    fn()
    return _ms(time.perf_counter() - started)


def _remote_storage(root):
    from vmn_exp.snapshot import LocalSnapshotStorage

    class Remote(LocalSnapshotStorage):
        def is_remote(self):
            return True

    return Remote(os.path.join(root, ".vmn", "store"), area="runs")


def _local_storage(root):
    from vmn_exp.snapshot import LocalSnapshotStorage

    return LocalSnapshotStorage(os.path.join(root, ".vmn", "store"), area="runs")


def _page(cache, snap, i):
    cache.page(snap, SCHEMA, sort="loss", limit=50, query=QUERIES[i % len(QUERIES)])


def _watch(index, cache, stop):
    """A browser on the board while the load runs: each published snapshot paged."""
    seen, i = None, 0
    while not stop.wait(0.2):
        snap = index._snapshot
        if snap is not None and snap is not seen:
            _page(cache, snap, i)
            seen, i = snap, i + 1


def _heap():
    return {"objects": len(gc.get_objects()), "frozen": gc.get_freeze_count()}


def _collections(pauses):
    stats = pauses.stats()
    return {"collections": stats["collections"], "max_ms": stats["max_ms"],
            "total_ms": stats["total_ms"], "pauses_ms": [r["ms"] for r in stats["recent"]]}


def _serve(index, cache, sec):
    """Steady state: board pages under each query and no-change refreshes."""
    deadline, i = time.monotonic() + sec, 0
    while time.monotonic() < deadline:
        if i % 20 == 19:
            index.refresh()
        _page(cache, index.snapshot(), i)
        i += 1
    return i


def _experiment(policy):
    if policy == "callback":
        clock = {}

        def freeze_after_slow(phase, info):
            if phase == "start":
                clock["t"] = time.perf_counter()
            elif time.perf_counter() - clock.get("t", 0) > 0.05:
                gc.freeze()

        gc.callbacks.append(freeze_after_slow)
    elif policy == "index":
        from vmn_exp.core import gc_pause
        from vmn_exp.core.index import ExperimentIndex

        real, grown = ExperimentIndex._publish_pending, {"rows": 0}

        def publish(self):
            real(self)
            rows = len(self._snapshot.rows) if self._snapshot else 0
            if rows >= max(2000, grown["rows"] * 1.25):
                grown["rows"] = rows
                gc_pause.freeze_long_lived()

        ExperimentIndex._publish_pending = publish
    elif policy == "threshold":
        gc.set_threshold(100_000, 10, 10)


def _case(kind, root, db, serve_sec):
    from vmn_exp.core.gc_pause import freeze_long_lived
    from vmn_exp.core.index import ExperimentIndex
    from vmn_exp.ui.diag.gc_pauses import GcPauses
    from vmn_exp.ui.leaderboard_cache import LeaderboardCache

    import scale_store

    pauses, out = GcPauses(recent=10_000), {"kind": kind}
    gc.callbacks.append(pauses.callback)
    _experiment(os.environ.get("GC_BENCH_POLICY"))
    started = time.perf_counter()
    cache = LeaderboardCache()
    if kind == "cold":
        index = ExperimentIndex(_remote_storage(root), scale_store.APP, cache_path=db)
        stop = threading.Event()
        watcher = threading.Thread(target=_watch, args=(index, cache, stop), daemon=True)
        watcher.start()
        index.refresh()
        stop.set()
        watcher.join()
    else:
        index = ExperimentIndex(_local_storage(root), scale_store.APP, cache_path=db)
        index.snapshot()
        index.wait_revalidated()
    cache.warm(index.snapshot())
    out["load_sec"] = round(time.perf_counter() - started, 1)
    out["rows"] = len(index.snapshot().rows)
    out["load"] = _collections(pauses)
    out["after_load"] = dict(_heap(), collect_ms=[_timed(gc.collect) for _ in range(2)])
    if serve_sec:
        pauses.__init__(recent=10_000)
        out["serve_requests"] = _serve(index, cache, serve_sec)
        out["serve"] = _collections(pauses)
    out["freeze_ms"] = _timed(freeze_long_lived)
    out["after_freeze"] = dict(_heap(), collect_ms=[_timed(gc.collect) for _ in range(2)])
    return out


def child(argv):
    kind, root, db, serve_sec, out = argv
    sys.path[:0] = [HERE] + SRC
    result = _case(kind, root, db, float(serve_sec))
    result.update(python=sys.version.split()[0],
                  gil=getattr(sys, "_is_gil_enabled", lambda: True)(),
                  threshold=list(gc.get_threshold()))
    with open(out, "w") as f:
        json.dump(result, f)


def _run(python, kind, root, db, serve_sec):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = f.name
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([HERE] + SRC))
    proc = subprocess.run([python, __file__, "--child", kind, root, db, str(serve_sec), out],
                          env=env, capture_output=True, text=True)
    if proc.returncode:
        return {"kind": kind, "error": proc.stderr[-2000:]}
    with open(out) as f:
        return json.load(f)


def bench(python, n, serve_sec):
    sys.path[:0] = [HERE] + SRC
    import scale_store

    root = scale_store.cached(n, progress=True)
    work = tempfile.mkdtemp(prefix="vmn-gc-bench-")
    db = os.path.join(work, "idx.sqlite")
    try:
        return [_run(python, "cold", root, db, serve_sec), _run(python, "warm", root, db, 0)]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", type=int, action="append", help="store sizes (default 100000)")
    p.add_argument("--python", action="append", help="interpreters (default this one)")
    p.add_argument("--serve-sec", type=float, default=60)
    a = p.parse_args(argv)
    for python in a.python or [sys.executable]:
        for n in a.runs or [100_000]:
            for result in bench(python, n, a.serve_sec):
                print(json.dumps(dict(result, runs=n)), flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        child(sys.argv[2:])
    else:
        main()
