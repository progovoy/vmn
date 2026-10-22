"""Seed s3bench's store: production-shaped records as S3 objects on disk.

    seed(data_dir, params) -> manifest

Writes ``<data>/shard-NNN.pkl`` (each a pickled ``[(key, mtime, bytes)]``,
keys relative to the store root) and ``<data>/manifest.json`` (the params,
the outer runs and the stuck runs). Every byte is a pure function of the
params and the seeding time kept in the manifest, so a reused ``--data``
dir serves identical objects to a baseline and a fixed run.

Shape (app ``fastglobalmacro``, store layout 2): three outer runs whose
subtrees hold 15 runs, about half of the runs and the rest, plus single
runs (a fifth). ``stuck`` runs (inner and single) claim ``running`` with a
heartbeat days old and keep their metrics uncompacted: ``segments`` synced
``.vms`` segments and as many log segments, as an SDK run's remote sync
leaves them. Finished runs carry one compacted ``.vmx`` (real codecs).
"""
import hashlib
import json
import math
import multiprocessing
import os
import pickle
import random
from array import array

import yaml

from uiload import seed_records, seeder
from uiload.seed_records import DAY, HEARTBEAT_SEC, iso
from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_files import indexed_name, stream_name
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.logfiles import log_object_name
from vmn_exp.core.step_metric import create_define_metric_entry
from vmn_exp.storage.store_marker import MARKER, new_marker

APP = "fastglobalmacro"
METRICS = ("loss", "val_loss", "sharpe", "drawdown", "turnover")
GOAL = ("sharpe", "max")
STEPS_PER_SEGMENT = 30  # one remote sync every 30 s at a step a second
SHARD_RUNS = 250


def layout(runs):
    """``[(kind, parent index or None)]`` of every run: three outer runs
    (15 inner, ~half, the rest), then the single runs."""
    singles = max(1, runs // 5)
    inner = runs - 3 - singles
    sizes = [min(15, inner)]
    sizes.append(min(runs // 2, inner - sizes[0]))
    sizes.append(inner - sum(sizes))
    roles = []
    for size in sizes:
        outer = len(roles)
        roles.append(("outer", None))
        roles += [("inner", outer)] * size
    return roles + [("single", None)] * singles


def stuck_indices(roles, stuck, seed):
    candidates = [i for i, (kind, _) in enumerate(roles) if kind != "outer"]
    return sorted(random.Random(f"{seed}:stuck").sample(candidates, min(stuck, len(candidates))))


def _stream(i):
    owner = hashlib.sha1(f"owner:{i}".encode()).hexdigest()[:8]
    return f"node-{i % 16:02d}~{owner}"


def _jsonl(entries):
    return "".join(json.dumps(e) + "\n" for e in entries).encode()


def _columns(i, first_step, steps, t0):
    step_axis = range(first_step, first_step + steps)
    ts = array("q", (int((t0 + s) * 1e6) for s in step_axis))
    out = {}
    for k, name in enumerate(METRICS):
        phase = i * 0.37 + k * 0.11
        out[name] = Columns(step_axis, ts, array("d", (
            math.exp(-s / 300.0) + 0.05 * math.sin(phase + s * 0.05) for s in step_axis)))
    return out


def _create_entries(i, t, rng, kind):
    if kind == "outer":
        params = {"sweep": f"sweep-{i}"}
    else:
        params = {"lr": round(10 ** rng.uniform(-5, -2), 6),
                  "lookback": rng.choice((20, 60, 120, 250)),
                  "universe": rng.choice(("g10", "em", "all")), "seed": i,
                  "model": rng.choice(("ridge", "gbm", "tcn")), "epochs": rng.randint(50, 500)}
    goal = create_define_metric_entry(GOAL[0], goal=GOAL[1])
    goal["timestamp"] = iso(t + 0.002)
    return [{"timestamp": iso(t + 0.001), "type": "create", "note": None, "params": params}, goal]


def _meta(i, roles, plan, t):
    kind, parent = roles[i]
    commit, code = seed_records.code_identity(i, plan["seed"])
    return {"verstr": seed_records.verstr_of(i, plan["seed"]), "code_verstr": code, "commit": commit,
            "timestamp": iso(t), "name": f"{kind}-{i:06d}", "archived": False,
            "parent": seed_records.verstr_of(parent, plan["seed"]) if parent is not None else None}


def _state(i, started, heartbeat, exit_code=None):
    state = {"state": "running", "runner": "sdk", "pid": 1000 + i, "host": f"node-{i % 16:02d}",
             "cwd": None, "started_at": iso(started), "heartbeat": iso(heartbeat),
             "heartbeat_seq": int((heartbeat - started) // HEARTBEAT_SEC),
             "heartbeat_interval_sec": HEARTBEAT_SEC}
    if exit_code is not None:
        state.update(state="finished", exit_code=exit_code, finished_at=iso(heartbeat),
                     duration_sec=round(heartbeat - started, 3))
    return state


def build_run(i, roles, stuck, plan):
    """``[(key relative to the run, mtime, bytes)]`` of run *i*."""
    rng = random.Random(f"{plan['seed']}:{i}")
    kind = roles[i][0]
    now, runs = plan["now"], len(roles)
    t = now - 30 * DAY + 27 * DAY * i / runs
    meta = _meta(i, roles, plan, t)
    stream = _stream(i)
    objs = [(".claim", t, b""),
            ("metadata.yml", t, seeder.metadata_yaml(APP, meta, format_version=2).encode())]
    entries = _create_entries(i, t, rng, kind)
    if i in stuck:
        end = now - rng.uniform(1, 3) * DAY  # the last heartbeat
        started = end - plan["segments"] * STEPS_PER_SEGMENT
        objs += _segments(i, stream, started, plan["segments"])
        state = _state(i, started, end)
    else:
        started = t + 1
        end = started + (60 if kind == "outer" else rng.randint(100, 400))
        if kind != "outer":
            steps = int(end - started)
            objs.append((indexed_name(stream, steps // STEPS_PER_SEGMENT), end,
                         build_index(stream, _columns(i, 0, steps, started))))
        state = _state(i, started, end, 0 if kind == "outer" or rng.random() < 0.88 else 1)
    objs.append((log_object_name(stream), started, _jsonl(entries)))
    objs.append(("run_state.yml", end, seeder.run_state_yaml(state).encode()))
    return meta["verstr"], objs


def _segments(i, stream, started, segments):
    """What a remote sync leaves of an uncompacted run: a metric block and
    (past the first, which holds the create entry) a log segment per sync."""
    objs = []
    for seq in range(segments):
        mtime = started + (seq + 1) * STEPS_PER_SEGMENT
        if seq:
            note = {"timestamp": iso(mtime), "type": "note", "text": f"epoch {seq} done"}
            objs.append((log_object_name(stream, seq), mtime, _jsonl([note])))
        block = encode_block(_columns(i, seq * STEPS_PER_SEGMENT, STEPS_PER_SEGMENT, started))
        objs.append((stream_name(stream, seq), mtime, block))
    return objs


def _plan_runs(plan):
    roles = layout(plan["runs"])
    return roles, set(stuck_indices(roles, plan["stuck"], plan["seed"]))


def write_shard(task):
    data, n, start, stop, plan = task
    roles, stuck = _plan_runs(plan)
    prefix = f"runs/{APP}"
    out = []
    for i in range(start, stop):
        verstr, objs = build_run(i, roles, stuck, plan)
        out += [(f"{prefix}/{verstr}/{name}", mtime, body) for name, mtime, body in objs]
    with open(os.path.join(data, f"shard-{n:04d}.pkl"), "wb") as f:
        pickle.dump(out, f, protocol=pickle.HIGHEST_PROTOCOL)
    return len(out)


def _write_marker(data, now):
    marker = dict(new_marker(), created_at=iso(now)[:19] + "Z")
    path = os.path.join(data, MARKER)
    with open(path, "w") as f:
        yaml.safe_dump(marker, f, sort_keys=False)
    os.utime(path, (now, now))


def seed(data, params, now, workers=os.cpu_count()):
    """Write the store of *params* into *data*; returns the manifest."""
    os.makedirs(data, exist_ok=True)
    plan = dict(params, now=now)
    roles, stuck = _plan_runs(plan)
    tasks = [(data, n, a, min(a + SHARD_RUNS, len(roles)), plan)
             for n, a in enumerate(range(0, len(roles), SHARD_RUNS))]
    with multiprocessing.get_context("spawn").Pool(max(1, workers or 1)) as pool:
        objects = sum(pool.imap_unordered(write_shard, tasks))
    _write_marker(data, now)
    verstr = lambda i: seed_records.verstr_of(i, params["seed"])  # noqa: E731
    outers = [i for i, (kind, _) in enumerate(roles) if kind == "outer"]
    manifest = {"params": params, "now": now, "app": APP, "objects": objects + 1,
                "goal": list(GOAL),
                "outers": [{"verstr": verstr(i), "runs": sum(1 for _, p in roles if p == i)}
                           for i in outers],
                "stuck": [verstr(i) for i in sorted(stuck)],
                "singles": sum(1 for kind, _ in roles if kind == "single")}
    with open(os.path.join(data, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def load_manifest(data, params):
    """The manifest in *data* when it was seeded with *params*, else None."""
    try:
        with open(os.path.join(data, "manifest.json")) as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return None
    return manifest if manifest.get("params") == params else None


def iter_objects(data):
    """Every seeded ``(key, mtime, bytes)``, the store marker first."""
    with open(os.path.join(data, MARKER), "rb") as f:
        yield MARKER, os.path.getmtime(f.name), f.read()
    for name in sorted(os.listdir(data)):
        if name.startswith("shard-"):
            with open(os.path.join(data, name), "rb") as f:
                yield from pickle.load(f)
