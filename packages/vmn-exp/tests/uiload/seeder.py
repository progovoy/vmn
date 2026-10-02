"""Bulk-seed historical experiment runs straight into local storage.

    seed(root, runs=100_000, sweeps=200, inner_per_sweep=50, ...) -> counts

writes ``<root>/.vmn/store/runs/<app>/<verstr>/`` records shaped exactly like
the SDK's git-free runs (see :mod:`uiload.seed_records`), sharded over worker
processes. Every run is a pure function of ``(rng_seed, index)``, so the counts
do not depend on *workers*. Seed into a fresh root: an existing record is an error.

    python packages/vmn-exp/tests/uiload/seeder.py <root> --runs 100000 --sweeps 200 --inner 50
"""
import argparse
import collections
import json
import multiprocessing
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uiload import seed_records

STATUSES = ("succeeded", "failed", "stuck", "created")
SHARDS_PER_WORKER = 4


def experiments_dir(root, app):
    return os.path.join(root, ".vmn", "store", "runs", app)


def metadata_yaml(app, meta):
    """``metadata.yml`` as yaml.dump writes it (sorted keys) for a from-snapshot run."""
    lines = [f"app_name: {app}"]
    if meta["archived"]:
        lines.append("archived: true")
    lines += [f"base_commit: {meta['commit']}", f"base_version: {seed_records.BASE_VERSION}",
              "branch: main", f"code_verstr: {meta['code_verstr']}", "dirty_states:",
              "- modified", "from_snapshot: true", "has_dep_patches: false",
              "has_local_commits_patch: false", "has_untracked_files: false",
              "has_working_tree_patch: false", f"name: {meta['name']}", "note: null"]
    if meta["parent"]:
        lines.append(f"parent: {meta['parent']}")
    lines += ["remote: null", f"timestamp: '{meta['timestamp']}'", f"verstr: {meta['verstr']}"]
    return "\n".join(lines) + "\n"


def _yaml_scalar(value):
    if isinstance(value, str) and value[:1].isdigit():
        return f"'{value}'"  # ISO timestamps: yaml.dump quotes them
    return str(value)


def run_state_yaml(state):
    """``run_state.yml`` in the SDK's key order (``sort_keys=False``)."""
    lines = []
    for key, value in state.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines += [f"- {item}" for item in value]
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def write_run(base, i, plan):
    """Write run *i*'s record; returns its metadata."""
    verstr, meta, entries, state = seed_records.build_run(i, plan)
    folder = os.path.join(base, verstr)
    os.mkdir(folder)
    _write(os.path.join(folder, "metadata.yml"), metadata_yaml(plan["app"], meta))
    writer = f"node-{i % 16:02d}"
    _write(os.path.join(folder, f"log/{writer}.jsonl"),
           "".join(json.dumps(e) + "\n" for e in entries))
    if state is not None:
        path = os.path.join(folder, "run_state.yml")
        _write(path, run_state_yaml(state))
        os.utime(path, (meta["last_write"], meta["last_write"]))
    return meta


def write_shard(task):
    """Write runs ``[start, stop)``; returns their counts."""
    plan, start, stop = task
    base = experiments_dir(plan["root"], plan["app"])
    counts = collections.Counter()
    for i in range(start, stop):
        meta = write_run(base, i, plan)
        counts[seed_records.status_of(i, plan)] += 1
        counts[seed_records.role(i, plan)[0]] += 1
        counts["archived"] += meta["archived"]
    return counts


def _shards(runs, n):
    size = max(1, -(-runs // n))
    return [(start, min(start + size, runs)) for start in range(0, runs, size)]


def _run_shards(tasks, workers):
    if workers <= 1:
        yield from map(write_shard, tasks)
        return
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        yield from pool.imap_unordered(write_shard, tasks)


def seed(root, app="loadapp", runs=1000, sweeps=0, inner_per_sweep=0,
         max_metric_keys=20, max_steps=1000, max_params=20, rng_seed=0,
         workers=os.cpu_count(), progress=False):
    """Seed *runs* historical runs (sweeps included) into *root*; returns counts."""
    if sweeps * (1 + inner_per_sweep) > runs:
        raise ValueError("sweeps * (1 + inner_per_sweep) exceeds runs")
    plan = {"root": os.path.abspath(root), "app": app, "runs": runs, "sweeps": sweeps,
            "inner": inner_per_sweep, "max_metric_keys": max_metric_keys,
            "max_steps": max_steps, "max_params": max_params, "seed": rng_seed,
            "now": time.time()}
    base = experiments_dir(plan["root"], app)
    os.makedirs(base, exist_ok=True)
    _write(os.path.join(base, ".gitignore"), "*\n")
    workers = max(1, min(workers or 1, runs // 20 or 1))
    tasks = [(plan, a, b) for a, b in _shards(runs, workers * SHARDS_PER_WORKER)]
    total, started = collections.Counter(), time.monotonic()
    for counts in _run_shards(tasks, workers):
        total.update(counts)
        if progress:
            done = total["single"] + total["outer"] + total["inner"]
            print(f"seeded {done}/{runs} ({done / (time.monotonic() - started):.0f} runs/s)",
                  file=sys.stderr, flush=True)
    result = {s: total[s] for s in STATUSES + ("outer", "inner", "archived")}
    result["total"] = runs
    return result


def seed_profile(root, profile, app="loadapp", **kwargs):
    """:func:`seed` sized by a scenario Profile (read by attribute)."""
    return seed(root, app=app, runs=profile.seeded_runs, sweeps=profile.seeded_sweeps,
                inner_per_sweep=profile.seeded_inner_per_sweep,
                max_metric_keys=profile.max_metric_keys, max_steps=profile.max_steps,
                max_params=profile.max_params, **kwargs)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root")
    p.add_argument("--app", default="loadapp")
    p.add_argument("--runs", type=int, default=10_000)
    p.add_argument("--sweeps", type=int, default=0)
    p.add_argument("--inner", type=int, default=0)
    p.add_argument("--max-metric-keys", type=int, default=50)
    p.add_argument("--max-steps", type=int, default=10_000)
    p.add_argument("--max-params", type=int, default=30)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=os.cpu_count())
    a = p.parse_args(argv)
    os.makedirs(os.path.join(a.root, ".git"), exist_ok=True)
    started = time.monotonic()
    counts = seed(a.root, app=a.app, runs=a.runs, sweeps=a.sweeps, inner_per_sweep=a.inner,
                  max_metric_keys=a.max_metric_keys, max_steps=a.max_steps,
                  max_params=a.max_params, rng_seed=a.seed, workers=a.workers, progress=True)
    print(json.dumps(dict(counts, seconds=round(time.monotonic() - started, 1))))


if __name__ == "__main__":
    main()
