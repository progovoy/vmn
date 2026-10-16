"""Plan 24 F1's similar-runs benchmark harness (not a test module).

    indexed_store(n) -> (store dir, index file)

builds the experiment index of :mod:`scale_store`'s *n*-run store once per
(store version, index schema, profile version, n), cached next to the store,
and :func:`measure` runs one query in a fresh process against a copy-free,
read-only use of that index file: *cold* is the process's first query, *warm*
its second, with the extra resident memory the query took.

    python packages/vmn-exp/tests/similar_bench.py <n>   # prints the numbers
"""
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SRC = [os.path.join(REPO, "packages", d, "src") for d in ("vmn", "vmn-exp-sdk", "vmn-exp")]
if __package__ in (None, ""):
    sys.path[:0] = [HERE] + SRC
import scale_store  # noqa: E402

APP = scale_store.APP
CONTEXT = " ".join(scale_store._VOCAB[100:120])


def _storage(store):
    from vmn_exp.snapshot import open_storage

    return open_storage(root=os.path.join(store, ".vmn", "store"), area="runs")


def indexed_store(n):
    """``(store root, index file)`` of the *n*-run store, the index built once."""
    from vmn_exp.core.index import ExperimentIndex
    from vmn_exp.core.index_store_schema import SCHEMA_VERSION
    from vmn_exp.core.similar_doc import PROFILE_VERSION

    store = scale_store.cached(n)
    name = f"index-v{scale_store.VERSION}-{SCHEMA_VERSION}-p{PROFILE_VERSION}-n{n}.sqlite"
    path = os.path.join(scale_store.cache_dir(), name)
    if not os.path.exists(path):
        building = tempfile.mkdtemp(prefix="index-", dir=scale_store.cache_dir())
        built = os.path.join(building, "index.sqlite")
        index = ExperimentIndex(_storage(store), APP, built, full_sweep_sec=0)
        index.refresh()
        index._store.close()
        os.replace(built, path)
        shutil.rmtree(building, ignore_errors=True)
    return store, path


def target_verstr(store):
    """A run of the store with an intent and changes: an inner run's first sibling."""
    from vmn_exp.core.index_store import SqliteStore

    _, path = store
    (verstr,) = SqliteStore(path)._conn.execute(
        "SELECT verstr FROM exp_rows WHERE app = ? AND parent IS NULL ORDER BY idx"
        " LIMIT 1 OFFSET 50", (APP,)).fetchone()
    return verstr


def _rss_mb():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1 << 20) if sys.platform == "darwin" else peak / 1024


def _query(store, path, kind, verstr):
    from vmn_exp.core.similar_corpus import file_scope
    from vmn_exp.core.similar_search import record_target, search, text_target

    storage = _storage(store)
    started = time.perf_counter()
    target = (text_target(CONTEXT) if kind == "text"
              else record_target(storage, APP, verstr))
    scope = file_scope(APP, path, repair=False)
    items = search(storage, APP, scope, target, top=10)
    return time.perf_counter() - started, len(items)


def child(store, path, kind, verstr):
    """This fresh process's imports, then (unless *kind* is ``import``) two
    queries: ``{imported_at, cold_at, in_process, warm, rss_mb, items}``
    (``*_at`` wall clock readings)."""
    import vmn_exp.cli.main  # noqa: F401  (what every vmn-exp command imports)
    import vmn_exp.core.similar_search  # noqa: F401
    import vmn_exp.snapshot  # noqa: F401

    out = {"imported_at": time.time()}
    if kind == "import":
        return out
    before = _rss_mb()
    out["in_process"], out["items"] = _query(store, path, kind, verstr)
    out["cold_at"], out["rss_mb"] = time.time(), _rss_mb() - before
    out["warm"] = _query(store, path, kind, verstr)[0]
    return out


def _spawn(store, path, kind, verstr):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(SRC))
    started = time.time()
    out = subprocess.run(
        [sys.executable, __file__, "--child", store, path, kind, verstr or ""],
        env=env, capture_output=True, text=True, check=True).stdout
    return started, json.loads(out.strip().splitlines()[-1])


def measure(store, path, kind, verstr=None, repeat=3):
    """A query in a fresh process: ``{wall, baseline, cold, warm, rss_mb,
    items}`` — *wall* from spawning it to its first answer, *baseline* the
    same for a process that only imports (Python start and the CLI's
    imports), *cold* the difference, *warm* a second query in that process,
    *rss_mb* the resident memory the first query added. Each the best of
    *repeat* runs: a shared machine only ever adds time."""
    baselines, runs = [], []
    for _ in range(repeat):
        started, imported = _spawn(store, path, "import", None)
        baselines.append(imported["imported_at"] - started)
        started, got = _spawn(store, path, kind, verstr)
        runs.append((got["cold_at"] - started, got))
    baseline, (wall, got) = min(baselines), min(runs, key=lambda r: r[0])
    return {"wall": wall, "baseline": baseline, "cold": wall - baseline,
            "warm": min(g["warm"] for _, g in runs), "in_process": got["in_process"],
            "rss_mb": max(g["rss_mb"] for _, g in runs), "items": got["items"]}


def snapshot_load(path):
    """Seconds a fresh process takes to load the persisted index's snapshot."""
    code = ("import sys, time; from vmn_exp.core.index import ExperimentIndex;"
            "from vmn_exp.core.index_store import SqliteStore;"
            "t = time.perf_counter(); ExperimentIndex.follower(SqliteStore(sys.argv[1]),"
            f" {APP!r}).snapshot(); print(time.perf_counter() - t)")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(SRC))
    out = subprocess.run([sys.executable, "-c", code, path], env=env, capture_output=True,
                         text=True, check=True).stdout
    return float(out.split()[-1])


def refile_seconds(store, path, count=100):
    """Seconds filing *count* runs whose intent changed takes in one save."""
    from vmn_exp.core.fold import fold_log
    from vmn_exp.core.log import load_log
    from vmn_exp.core.similar_filing import file_records
    from vmn_exp.core.sqlite_conn import connect, write_tx

    work = tempfile.mkdtemp(prefix="similar-refile-")
    try:
        copy = os.path.join(work, "index.sqlite")
        shutil.copyfile(path, copy)
        conn = connect(copy)
        storage = _storage(store)
        keys = [k for (k,) in conn.execute(
            "SELECT key FROM exp_rows WHERE app = ? ORDER BY idx LIMIT ?", (APP, count))]
        changed = {}
        for key in keys:
            entry = {"type": "intent", "text": "a new direction " + key, "source": "user",
                     "timestamp": "2099-01-01T00:00:00Z"}
            fold = fold_log(list(load_log(storage, APP, key)) + [entry])
            changed[key] = {"meta": storage.load_metadata(APP, key), "fold": fold,
                            "run_state": None, "rs_sig": None}
        started = time.perf_counter()
        with write_tx(conn):
            file_records(conn, APP, changed, ())
        return time.perf_counter() - started
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        print(json.dumps(child(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] or None)))
    else:
        n = int(sys.argv[1])
        started = time.monotonic()
        built = indexed_store(n)
        print(f"index ready in {time.monotonic() - started:.1f}s: {built[1]}")
        verstr = target_verstr(built)
        print("full", measure(*built, "run", verstr))
        print("text", measure(*built, "text"))
        print("refile 100", refile_seconds(*built))
        print("snapshot load", snapshot_load(built[1]))
