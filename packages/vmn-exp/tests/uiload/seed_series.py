"""Seed a ``bigseries`` profile: finished runs whose metrics are written
straight as compacted ``metrics/<writer>.vmx`` files (plan 12 §3.2), built
with the real codec (:func:`vmn_exp.core.metric_index_file.build_index`)
instead of logging millions of points through the SDK.

    seed_profile(root, scenario.get_series_profile("bigseries-tiny")) -> counts

Runs are ``big-NNNN`` (long series), ``wide-NNNN`` (many keys) and
``overlay-NNNN`` (the comparison chart's population; every run logs ``loss``).
Records are format 2: the JSONL log carries create/run entries only.

    python packages/vmn-exp/tests/uiload/seed_series.py <root> --profile bigseries
"""
import argparse
import json
import math
import multiprocessing
import os
import sys
import time
from array import array

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uiload import scenario, seed_records, seeder
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import indexed_name
from vmn_exp.core.metric_index_file import build_index

WRITER = "seed"
STEP_USEC = 100_000  # 10 steps per second of wall clock
GROUPS = ("big", "wide", "overlay")


def metric_names(n):
    head = ["loss", "acc", "val_loss", "val_acc"][:n]
    return head + [f"m_{k:04d}" for k in range(n - len(head))]


def _series(key_index, steps, run_index):
    phase = run_index * 0.37 + key_index * 0.11
    decay = 3.0 / steps
    return (math.exp(-decay * s) + 0.01 * math.sin(phase + s * 0.05) for s in range(steps))


def build_columns(run_index, steps, n_keys, start_usec):
    """``{key: Columns}`` of one run: every key logged at every step."""
    step_axis = range(steps)
    ts = array("q", (start_usec + s * STEP_USEC for s in step_axis))
    return {name: Columns(step_axis, ts, array("d", _series(k, steps, run_index)))
            for k, name in enumerate(metric_names(n_keys))}


def plan_runs(profile):
    """``[(group, index within group, steps, keys)]`` in seeding order."""
    sizes = {"big": (profile.big_runs, profile.big_steps, profile.big_keys),
             "wide": (profile.wide_runs, profile.wide_steps, profile.wide_keys),
             "overlay": (profile.overlay_runs, profile.overlay_steps, 1)}
    return [(group, j, steps, keys)
            for group in GROUPS for j in range(sizes[group][0])
            for steps, keys in [sizes[group][1:]]]


def _write(path, data, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(data)


def write_run(task):
    """Write one finished run's record (metadata, log, run_state, ``.vmx``)."""
    root, app, i, (group, j, steps, n_keys), now = task
    verstr = seed_records.verstr_of(i, 0)
    commit, code = seed_records.code_identity(i, 0)
    started = now - 30 * seed_records.DAY + i
    end = started + steps * STEP_USEC / 1e6
    meta = {"verstr": verstr, "code_verstr": code, "commit": commit,
            "timestamp": seed_records.iso(started), "name": f"{group}-{j:04d}",
            "archived": False, "parent": None}
    folder = os.path.join(seeder.experiments_dir(root, app), verstr)
    os.mkdir(folder)
    _write(os.path.join(folder, "metadata.yml"), seeder.metadata_yaml(app, meta, format_version=2))
    command = ["python", "train.py", "--group", group]
    lines = [{"timestamp": seed_records.iso(started), "type": "create", "note": None,
              "params": {"group": group}},
             {"timestamp": seed_records.iso(end), "type": "run", "command": command,
              "exit_code": 0, "duration_sec": round(end - started, 3)}]
    _write(os.path.join(folder, f"log/{WRITER}.jsonl"), "".join(json.dumps(e) + "\n" for e in lines))
    state = {"state": "finished", "command": command, "pid": 1000 + i, "host": WRITER,
             "started_at": seed_records.iso(started), "heartbeat": seed_records.iso(end),
             "heartbeat_seq": 0, "heartbeat_interval_sec": seed_records.HEARTBEAT_SEC,
             "exit_code": 0, "finished_at": seed_records.iso(end),
             "duration_sec": round(end - started, 3)}
    _write(os.path.join(folder, "run_state.yml"), seeder.run_state_yaml(state))
    keys = build_columns(i, steps, n_keys, int(started * 1e6))
    _write(os.path.join(folder, indexed_name(WRITER)), build_index(WRITER, keys), mode="wb")
    return group


def _map(tasks, workers):
    if workers <= 1:
        yield from map(write_run, tasks)
        return
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        yield from pool.imap_unordered(write_run, tasks)


def seed_profile(root, profile, app="loadapp", workers=os.cpu_count(), progress=False):
    """Seed *profile* into a fresh *root*; returns ``{group: runs, "total": n}``."""
    root = os.path.abspath(root)
    base = seeder.experiments_dir(root, app)
    os.makedirs(base, exist_ok=True)
    _write(os.path.join(base, ".gitignore"), "*\n")
    now = time.time()
    tasks = [(root, app, i, run, now) for i, run in enumerate(plan_runs(profile))]
    counts = dict.fromkeys(GROUPS, 0)
    for done, group in enumerate(_map(tasks, max(1, workers or 1)), 1):
        counts[group] += 1
        if progress:
            print(f"seeded {done}/{len(tasks)}", file=sys.stderr, flush=True)
    return dict(counts, total=len(tasks))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root")
    p.add_argument("--profile", default="bigseries", choices=sorted(scenario.SERIES_PROFILES))
    p.add_argument("--app", default="loadapp")
    p.add_argument("--workers", type=int, default=os.cpu_count())
    a = p.parse_args(argv)
    os.makedirs(os.path.join(a.root, ".git"), exist_ok=True)
    started = time.monotonic()
    counts = seed_profile(a.root, scenario.get_series_profile(a.profile), app=a.app,
                          workers=a.workers, progress=True)
    print(json.dumps(dict(counts, seconds=round(time.monotonic() - started, 1))))


if __name__ == "__main__":
    main()
