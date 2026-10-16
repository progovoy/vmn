"""Baselines for plan 25 §1 (and plan 24's similar budgets) against a
synthetic store of N runs (:mod:`scale_store`). Not a pytest test.

Each case runs in a fresh process inside a minimal checkout whose
``.vmn/store`` links to the cached store: *cold* with an empty
``VMN_EXP_CACHE_DIR`` (the index is built from the store), then *warm*, the
same command again on the index the cold run left. Wall time is the whole
process as a user sees it; peak RSS is the child's own ``ru_maxrss``.

    python packages/vmn-exp/tests/bench_scale.py --runs 20000 --runs 100000
"""
import argparse
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
sys.path[:0] = [HERE] + SRC
import scale_store  # noqa: E402
from uiload import seed_records  # noqa: E402

TAIL = 400


def _rss_mb():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1 << 20) if sys.platform == "darwin" else peak / 1024


def child(kind, payload, out):
    """Run one case in this process; write ``{rss_mb, rc}`` to *out*."""
    rc = 0
    if kind == "cli":
        from vmn_exp.cli.main import main

        sys.argv = ["vmn-exp", *payload]
        try:
            rc = main() or 0
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    elif kind == "get_run":
        from vmn_exp.sdk.reader import get_run

        get_run(scale_store.APP, payload[0])
    elif kind == "noop":
        import vmn_exp.cli.main  # noqa: F401  (the import cost every case pays)
    with open(out, "w") as f:
        json.dump({"rss_mb": _rss_mb(), "rc": rc}, f)


def checkout(store_root):
    """A throwaway git checkout whose ``.vmn/store`` is the cached store."""
    work = tempfile.mkdtemp(prefix="vmn-bench-scale-")
    run = lambda *a: subprocess.run(["git", *a], cwd=work, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    run("-c", "user.email=bench@vmn", "-c", "user.name=bench", "commit", "-q", "--allow-empty", "-m", "init")
    os.mkdir(os.path.join(work, ".vmn"))
    os.symlink(os.path.join(store_root, ".vmn", "store"), os.path.join(work, ".vmn", "store"))
    return work


def measure(work, cache, kind, payload):
    out = os.path.join(work, "result.json")
    env = dict(os.environ, VMN_EXP_CACHE_DIR=cache, PYTHONPATH=os.pathsep.join(SRC))
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, __file__, "--child", kind, out, json.dumps(payload)],
                          cwd=work, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - started
    result = {"wall": wall, "rc": proc.returncode, "rss_mb": None, "err": proc.stderr[-TAIL:]}
    if os.path.exists(out):
        result.update(json.load(open(out)))
        os.remove(out)
    if proc.returncode == 0 and result["rc"]:
        result["err"] = (proc.stdout + proc.stderr)[-TAIL:]
    return result


def cases(n):
    exact = seed_records.verstr_of(n // 2, 0)
    words = " ".join(scale_store._VOCAB[100:120])
    app = scale_store.APP
    return [
        ("import only (vmn_exp.cli.main)", "noop", []),
        ("vmn-exp show -v <exact>", "cli", ["show", app, "-v", exact]),
        ("reader.get_run(<exact>)", "get_run", [exact]),
        ("vmn-exp list --last 20", "cli", ["list", app, "--last", "20"]),
        ('vmn-exp list --query \'status = "failed"\'', "cli", ["list", app, "--query", 'status = "failed"']),
        ("vmn-exp similar --text-only --context", "cli", ["similar", app, "--text-only", "--context", words]),
    ]


def bench(n, workers):
    store = scale_store.cached(n, workers=workers, progress=True)
    work = checkout(store)
    rows = []
    try:
        for label, kind, payload in cases(n):
            cache = tempfile.mkdtemp(prefix="cache-", dir=work)
            cold = measure(work, cache, kind, payload)
            warm = measure(work, cache, kind, payload)
            rows.append((label, cold, warm))
            print(f"  {n} {label}: cold {cold['wall']:.2f}s warm {warm['wall']:.2f}s", file=sys.stderr, flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return rows


def _cell(r):
    if r["rc"]:
        return f"FAILED rc={r['rc']}"
    return f"{r['wall']:.2f} s / {r['rss_mb']:.0f} MB"


def report(n, rows):
    print(f"\n### {n:,} runs\n")
    print("| case | cold: wall / peak RSS | warm: wall / peak RSS |")
    print("|---|---|---|")
    for label, cold, warm in rows:
        print(f"| `{label}` | {_cell(cold)} | {_cell(warm)} |")
    for label, cold, warm in rows:
        for name, r in (("cold", cold), ("warm", warm)):
            if r["rc"]:
                print(f"\n{label} ({name}) failed:\n{r['err']}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", type=int, action="append", help="store sizes (repeatable; default 100000)")
    p.add_argument("--workers", type=int, default=None, help="generator processes")
    a = p.parse_args(argv)
    for n in a.runs or [100_000]:
        report(n, bench(n, a.workers))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        child(sys.argv[2], json.loads(sys.argv[4]), sys.argv[3])
    else:
        main()
