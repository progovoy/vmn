"""Seed fgm's run tree (plan 28 B0, :mod:`uiload.fgm_tree`) as a layout-2
store: ``<root>/.vmn/store/`` (``store.yml`` + ``runs/fastglobalmacro/``),
one record per planned run (:mod:`uiload.fgm_records`), a slice of a launch
per task over worker processes, then ``<root>/fgm-seed.json`` (profile, ``now``,
``total``, ``fates``).

    seed(root, fgm_tree.get_profile("fgm-tiny")) -> manifest

``run_state.yml``'s mtime is the run's last write, so orphans read stale to
the store too. Live runs beat at seeding time with a heartbeat interval of
:data:`LIVE_INTERVAL_SEC`, so they read ``running`` for months while the
orphans read ``stuck``. The full ``fgm`` profile (~594k runs, ~1.8M files)
takes about an hour on a laptop's APFS:

    python packages/vmn-exp/tests/uiload/seed_fgm.py /tmp/fgm --profile fgm
    vmn-exp ui --repo /tmp/fgm
"""
import argparse
import collections
import json
import multiprocessing
import os
import sys
import time

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.store_marker import MARKER, new_marker

from uiload import fgm_records, fgm_tree
from uiload.seeder import _write

MANIFEST = "fgm-seed.json"
LIVE_INTERVAL_SEC = 120 * 86400  # stale after 3 missed beats: a year
WRITER = "fgm-pod"
_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def _yaml(data):
    return yaml.dump(data, Dumper=_DUMPER, sort_keys=False, default_flow_style=False)


def seeded_run_state(spec, now):
    """*spec*'s ``run_state.yml`` as seeded (live runs beating rarely)."""
    return fgm_records.run_state(spec, now, LIVE_INTERVAL_SEC)


def write_run(base, spec, now, app):
    meta, entries, state = fgm_records.build_run(spec, now, app, LIVE_INTERVAL_SEC)
    folder = os.path.join(base, spec["verstr"])
    _write(os.path.join(folder, "metadata.yml"), _yaml(meta))
    _write(os.path.join(folder, "log", f"{WRITER}.jsonl"),
           "".join(json.dumps(e) + "\n" for e in entries))
    if state is not None:
        path = os.path.join(folder, "run_state.yml")
        _write(path, _yaml(state))
        written = fgm_records.last_write(spec, now)
        os.utime(path, (written, written))


def write_part(task):
    """Write every *parts*-th record of launch *n* from *part* on; their fates."""
    root, profile, n, part, parts, now, app = task
    base = os.path.join(local_store_root(root), "runs", app)
    fates = collections.Counter()
    for spec in fgm_tree.launch_runs(profile, n, now)[part::parts]:
        write_run(base, spec, now, app)
        fates[spec["fate"]] += 1
    return fates


def _parts(tasks, workers):
    if workers <= 1:
        yield from map(write_part, tasks)
        return
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        yield from pool.imap_unordered(write_part, tasks)


def seed(root, profile, app=fgm_records.APP, workers=None, now=None, progress=False):
    """Seed *profile* into a fresh *root* as of *now* (default: now)."""
    root, now = os.path.abspath(root), time.time() if now is None else now
    store = local_store_root(root)
    os.makedirs(os.path.join(store, "runs", app))
    _write(os.path.join(store, ".gitignore"), "*\n")
    _write(os.path.join(store, MARKER), yaml.safe_dump(new_marker()))
    workers = max(1, workers or os.cpu_count() or 1)
    parts = max(1, -(-workers * 2 // profile.launches))
    tasks = [(root, profile, n, k, parts, now, app)
             for n in range(profile.launches) for k in range(parts)]
    fates = collections.Counter()
    for done, counts in enumerate(_parts(tasks, min(workers, len(tasks))), 1):
        fates.update(counts)
        if progress:
            print(f"seeded part {done}/{len(tasks)} ({sum(fates.values())} runs)",
                  file=sys.stderr, flush=True)
    manifest = {"profile": profile.name, "app": app, "now": now,
                "total": sum(fates.values()), "fates": dict(fates)}
    _write(os.path.join(root, MANIFEST), json.dumps(manifest))
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root")
    p.add_argument("--profile", default="fgm", choices=sorted(fgm_tree.PROFILES))
    p.add_argument("--app", default=fgm_records.APP)
    p.add_argument("--workers", type=int, default=os.cpu_count())
    a = p.parse_args(argv)
    os.makedirs(os.path.join(a.root, ".git"), exist_ok=True)
    started = time.monotonic()
    manifest = seed(a.root, fgm_tree.get_profile(a.profile), app=a.app, workers=a.workers,
                    progress=True)
    print(json.dumps(dict(manifest, seconds=round(time.monotonic() - started, 1))))


if __name__ == "__main__":
    main()
