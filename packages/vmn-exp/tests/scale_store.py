"""A synthetic large experiment store (plan 25 F0, shared with plan 24 F1).

    generate(root, n) -> expected counts
    cached(n) -> root of a generated store, reused across test sessions

writes ``<root>/.vmn/store/`` in store layout 2 (``store.yml`` + the ``runs/``
area) with *n* format-2 runs of one app, sharded over worker processes. Each
run has ``metadata.yml``, a JSONL log (create with params, ``features`` with
changed files and symbols, ``intent`` with ~150 words of a 20k-word vocabulary
and 5 keywords, run/error entries), its metrics as one compacted ``.vmx`` and,
unless it never ran, ``run_state.yml``. Every 100 runs open with an outer run
whose next 33 runs are its inner runs, so a third of the runs have a parent.
Statuses mix succeeded, failed and running (a fresh heartbeat: in a store
reused from the cache, running runs read stuck once their heartbeat is stale).

    python packages/vmn-exp/tests/scale_store.py <n>   # prints the cached root
"""
import collections
import itertools
import json
import multiprocessing
import os
import random
import shutil
import sys
import tempfile
import time
from array import array

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uiload import seed_records, seeder
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import indexed_name
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.storage.store_marker import MARKER, new_marker

VERSION = 1  # bump when the generated content changes: cached stores are keyed by it
APP = "scaleapp"
COMPLETE = ".scale-store-complete"
BLOCK, INNER_PER_BLOCK = 100, 33
VOCABULARY_SIZE, INTENT_WORDS, KEYWORDS = 20_000, 150, 5
STEPS, METRICS = 20, ("loss", "acc", "val_loss")
MODULES, FILES_PER_MODULE = 200, 10
STATUS_WEIGHTS = {"succeeded": 75, "failed": 15, "running": 10}
_SYLLABLES = [c + v for c in "bcdfghjklmnprstvwxz" for v in "aeiou"]


def vocabulary(size=VOCABULARY_SIZE):
    """*size* distinct pseudo-words, the same on every call."""
    rng, words = random.Random(1), {}
    while len(words) < size:
        words.setdefault("".join(rng.choices(_SYLLABLES, k=rng.randint(2, 4))), None)
    return list(words)


_VOCAB = vocabulary()
_ZIPF = list(itertools.accumulate(1 / (rank + 1) for rank in range(VOCABULARY_SIZE)))


def role(i):
    """``(kind, outer index or None)`` of run *i*."""
    offset = i % BLOCK
    if offset == 0:
        return "outer", None
    return ("inner", i - offset) if offset <= INNER_PER_BLOCK else ("single", None)


def status_of(i):
    rng = random.Random(i * 7919 + 13)
    return rng.choices(list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values()))[0]


def _intent(rng):
    words = rng.choices(_VOCAB, cum_weights=_ZIPF, k=rng.randint(140, 160))
    return {"type": "intent", "text": " ".join(words),
            "keywords": rng.sample(_VOCAB[:2000], KEYWORDS), "source": "user"}


def _features(rng):
    files = sorted({f"src/mod_{rng.randrange(MODULES):03d}/file_{rng.randrange(FILES_PER_MODULE)}.py"
                    for _ in range(rng.randint(1, 5))})
    symbols = [f"{path}::fn_{rng.randrange(50)}" for path in files for _ in range(rng.randint(1, 3))]
    return {"type": "features", "features_version": FEATURES_VERSION, "source": "capture",
            "changed": {"files": files, "symbols": sorted(set(symbols))},
            "commits": [f"tune {rng.choice(_VOCAB)} {rng.choice(_VOCAB)}"]}


def _metric_columns(rng, start):
    steps = range(STEPS)
    ts = array("q", (int((start + s) * 1e6) for s in steps))
    return {key: Columns(steps, ts, array("d", (rng.random() for _ in steps))) for key in METRICS}


def build_run(i, now, n):
    """``(verstr, metadata, log entries, metric columns, run_state, status)`` of run *i*."""
    rng, status = random.Random(i), status_of(i)
    kind, outer = role(i)
    commit, code = seed_records.code_identity(i, 0)
    verstr = seed_records.verstr_of(i, 0)
    t = now - 60 * seed_records.DAY + 59 * seed_records.DAY * i / n
    params = {"lr": round(10 ** rng.uniform(-5, -1), 6), "batch_size": rng.choice((16, 32, 64)),
              "optimizer": rng.choice(seed_records.OPTIMIZERS), "model": rng.choice(seed_records.MODELS),
              "epochs": rng.randint(1, 100), "seed": rng.randint(0, 9999)}
    meta = {"verstr": verstr, "code_verstr": code, "commit": commit, "timestamp": seed_records.iso(t),
            "name": f"scale-{i:06d}", "archived": False,
            "parent": seed_records.verstr_of(outer, 0) if outer is not None else None}
    stamp = lambda dt: seed_records.iso(t + dt)  # noqa: E731
    entries = [{"timestamp": stamp(0.001), "type": "create", "note": None, "params": params},
               dict(_features(rng), timestamp=stamp(0.002)), dict(_intent(rng), timestamp=stamp(0.003))]
    command = ["python", "train.py", "--model", params["model"]]
    state = {"state": "running", "command": command, "pid": 1000 + i, "host": f"node-{i % 16:02d}",
             "started_at": stamp(0.5), "heartbeat": seed_records.iso(now),
             "heartbeat_seq": 1, "heartbeat_interval_sec": seed_records.HEARTBEAT_SEC}
    if status != "running":
        exit_code = 0 if status == "succeeded" else 1
        if exit_code:
            entries.append({"timestamp": stamp(STEPS), "type": "error",
                            "exception": "RuntimeError", "message": "loss is NaN"})
        entries.append({"timestamp": stamp(STEPS + 0.1), "type": "run", "command": command,
                        "exit_code": exit_code, "duration_sec": STEPS})
        state.update(state="finished", heartbeat=stamp(STEPS), exit_code=exit_code,
                     finished_at=stamp(STEPS + 0.2), duration_sec=STEPS)
    return verstr, meta, entries, _metric_columns(rng, t + 0.5), state, status


def _write(path, data, mode="w"):
    with open(path, mode) as f:
        f.write(data)


def write_run(base, i, now, n):
    verstr, meta, entries, columns, state, status = build_run(i, now, n)
    folder = os.path.join(base, verstr)
    writer = state["host"]
    for sub in ("log", "metrics"):
        os.makedirs(os.path.join(folder, sub))
    _write(os.path.join(folder, "metadata.yml"), seeder.metadata_yaml(APP, meta, format_version=2))
    _write(os.path.join(folder, "log", f"{writer}.jsonl"), "".join(json.dumps(e) + "\n" for e in entries))
    _write(os.path.join(folder, indexed_name(writer)), build_index(writer, columns), mode="wb")
    _write(os.path.join(folder, "run_state.yml"), seeder.run_state_yaml(state))
    return status


def write_shard(task):
    """Write runs ``[start, stop)``; returns their status and role counts."""
    root, start, stop, now, n = task
    base = os.path.join(root, "runs", APP)
    counts = collections.Counter()
    for i in range(start, stop):
        counts[write_run(base, i, now, n)] += 1
        counts[role(i)[0]] += 1
    return counts


def _store_root(root):
    return os.path.join(root, ".vmn", "store")


def _write_marker(store):
    os.makedirs(os.path.join(store, "runs", APP))
    _write(os.path.join(store, ".gitignore"), "*\n")
    _write(os.path.join(store, MARKER), yaml.safe_dump(new_marker()))


def generate(root, n, workers=None, progress=False, now=None):
    """Write *n* runs of ``APP`` into a fresh *root*, as of wall time *now*
    (default: now); returns the expected counts."""
    store = _store_root(os.path.abspath(root))
    _write_marker(store)
    workers = max(1, min(workers or os.cpu_count() or 1, n // 50 or 1))
    size = max(1, -(-n // (workers * 8)))
    now = time.time() if now is None else now
    tasks = [(store, a, min(a + size, n), now, n) for a in range(0, n, size)]
    total = collections.Counter()
    shards = map(write_shard, tasks)
    pool = multiprocessing.get_context("spawn").Pool(workers) if workers > 1 else None
    if pool:
        shards = pool.imap_unordered(write_shard, tasks)
    try:
        for counts in shards:
            total.update(counts)
            if progress:
                print(f"generated {sum(total[s] for s in STATUS_WEIGHTS)}/{n}", file=sys.stderr, flush=True)
    finally:
        if pool:
            pool.close()
            pool.join()
    return {"total": n, "outer": total["outer"], "inner": total["inner"],
            "statuses": {s: total[s] for s in STATUS_WEIGHTS if total[s]}}


def cache_dir():
    return os.environ.get("VMN_SCALE_STORE_DIR") or os.path.join(tempfile.gettempdir(), "vmn-scale-store")


def cached(n, workers=None, progress=False):
    """The root of an *n*-run store, generated once per (``VERSION``, *n*)."""
    root = os.path.join(cache_dir(), f"v{VERSION}-n{n}")
    if os.path.exists(os.path.join(root, COMPLETE)):
        return root
    os.makedirs(cache_dir(), exist_ok=True)
    building = tempfile.mkdtemp(prefix=f"v{VERSION}-n{n}.", dir=cache_dir())
    expected = generate(building, n, workers=workers, progress=progress)
    _write(os.path.join(building, COMPLETE), json.dumps(expected))
    try:
        os.rename(building, root)
    except OSError:  # another session finished first
        shutil.rmtree(building, ignore_errors=True)
    return root


if __name__ == "__main__":
    started = time.monotonic()
    print(cached(int(sys.argv[1]), progress=True))
    print(f"{time.monotonic() - started:.1f}s", file=sys.stderr)
