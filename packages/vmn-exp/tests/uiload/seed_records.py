"""One seeded historical run: its plan (pure function of its index) and its files.

Stdlib only, so the seeder's worker processes start fast. The files mirror what
``vmn_exp.sdk.start_run`` writes in git-free mode: ``metadata.yml`` (identity,
``name``, ``parent``, ``archived``), ``log.<writer>.jsonl`` (create/tags/metrics/
error/run entries; params ride on the create entry) and ``run_state.yml``, whose
mtime is set to the last heartbeat so a stuck run reads stale to the store too.
"""
import hashlib
import math
import random
import time

DAY = 86400
RUNS_PER_CODE = 100  # runs sharing one code state: verstr, then verstr.r2, .r3 ...
BASE_VERSION = "1.4.0"
HEARTBEAT_SEC = 30
OPTIMIZERS = ("adam", "adamw", "sgd", "lion")
MODELS = ("resnet18", "resnet50", "vit_b16", "bert_base", "gpt2_small")
TEAMS = ("vision", "nlp", "infra")
STAGES = ("baseline", "ablation", "tuning", "final")
NAMED_METRICS = ("loss", "acc", "val_loss", "val_acc", "f1", "lr_now")
FAILURES = (("RuntimeError", "CUDA error: device-side assert triggered", 1),
            ("ValueError", "loss is NaN", 1), (None, None, 137), (None, None, 143))


def role(i, plan):
    """``(kind, outer index or None)`` of run *i*: sweeps come first, in blocks."""
    block = 1 + plan["inner"]
    if i >= plan["sweeps"] * block:
        return "single", None
    offset = i % block
    return ("outer", None) if offset == 0 else ("inner", i - offset)


def code_identity(i, seed):
    group = i // RUNS_PER_CODE
    commit = hashlib.sha1(f"{seed}:commit:{group}".encode()).hexdigest()
    diff = hashlib.sha1(f"{seed}:diff:{group}".encode()).hexdigest()
    return commit, f"{BASE_VERSION}-dev.{commit[:7]}.{diff[:7]}"


def verstr_of(i, seed):
    code = code_identity(i, seed)[1]
    run = i % RUNS_PER_CODE + 1
    return code if run == 1 else f"{code}.r{run}"


def _rng(i, plan):
    return random.Random(plan["seed"] * 1_000_003 + i)


def _pick(rng, weights):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def status_of(i, plan):
    kind, outer = role(i, plan)
    if kind == "inner" and status_of(outer, plan) == "stuck":
        return "stuck"  # the process hosting the whole sweep died
    weights = {"succeeded": 80, "failed": 10, "stuck": 5, "created": 5}
    if kind == "outer":
        weights = {"succeeded": 80, "failed": 12, "stuck": 8}
    return _pick(_rng(i, plan), weights)


def _count(rng, typical, cap):
    """Mostly *typical* (a range), with a rare long tail reaching *cap*."""
    if rng.random() < 0.05:
        return rng.randint(min(typical[1], cap), cap)
    return min(rng.randint(*typical), cap)


LONG_EVERY = 500  # one run in this many gets a series near max_steps


def _steps(i, rng, cap):
    """20-200 steps for most runs; 3% reach cap/5, and every LONG_EVERY-th near cap."""
    if i % LONG_EVERY == LONG_EVERY // 2:
        return rng.randint(cap // 2, cap)
    if rng.random() < 0.03:
        return min(int(200 * max(cap / 1000, 1) ** rng.random()), cap)
    return min(int(20 * 10 ** rng.random()), cap)


def _param(rng, k):
    typed = (lambda: round(10 ** rng.uniform(-5, -1), 6), lambda: rng.choice((16, 32, 64, 128)),
             lambda: rng.choice(OPTIMIZERS), lambda: rng.random() < 0.5)
    return typed[k % 4]()


def make_params(rng, cap):
    named = {
        "lr": round(10 ** rng.uniform(-5, -1), 6), "batch_size": rng.choice((16, 32, 64, 128)),
        "optimizer": rng.choice(OPTIMIZERS), "use_amp": rng.random() < 0.5,
        "model": rng.choice(MODELS), "epochs": rng.randint(1, 100),
        "dropout": round(rng.uniform(0, 0.5), 3), "seed": rng.randint(0, 9999),
    }
    n = _count(rng, (4, 12), cap)
    params = dict(list(named.items())[:n])
    for k in range(n - len(params)):
        params[f"p_{k:03d}"] = _param(rng, k)
    return params


def metric_keys(rng, cap):
    n = _count(rng, (3, 8), cap)
    keys = list(NAMED_METRICS[:n])
    return keys + [f"m_{k:03d}" for k in range(n - len(keys))]


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t % 1 * 1e6):06d}Z"


def _value(rng, key, frac):
    base = math.exp(-3 * frac) if "loss" in key else 1 - 0.9 * math.exp(-3 * frac)
    return round(base + rng.gauss(0, 0.02), 6)


def build_run(i, plan):
    """Everything to write for run *i*: ``(verstr, metadata, log lines, run_state)``."""
    rng, status = _rng(i, plan), status_of(i, plan)
    kind, outer = role(i, plan)
    commit, code = code_identity(i, plan["seed"])
    verstr = verstr_of(i, plan["seed"])
    # start times spread over [now - 60 days, now - 1 day], oldest first
    t = plan["now"] - 60 * DAY + 59 * DAY * i / plan["runs"] + rng.uniform(0, 60)
    params, keys = make_params(rng, plan["max_params"]), metric_keys(rng, plan["max_metric_keys"])
    meta = {"verstr": verstr, "code_verstr": code, "commit": commit, "timestamp": iso(t),
            "name": f"hist-{i:06d}", "archived": kind == "single" and i % 50 == 25,
            "parent": verstr_of(outer, plan["seed"]) if outer is not None else None}
    lines = [{"timestamp": iso(t + 0.001), "type": "create", "note": None, "params": params}]
    if rng.random() < 0.15:
        lines.append({"timestamp": iso(t + 0.002), "type": "tags",
                      "set": {"team": rng.choice(TEAMS), "stage": rng.choice(STAGES)}})
    if status == "created":
        return verstr, meta, lines, None
    steps = max(1, _steps(i, rng, plan["max_steps"]))
    if status in ("failed", "stuck"):
        steps = max(1, int(steps * rng.uniform(0.1, 0.9)))
    diverge = steps // 2 if rng.random() < 0.03 else None
    dt = rng.uniform(0.5, 5.0)
    started = t + 0.5
    for s in range(steps):
        values = {k: _value(rng, k, s / steps) for k in keys[:3]}
        if diverge is not None and s >= diverge:
            values[keys[0]] = rng.choice((float("nan"), float("inf")))
        lines.append({"timestamp": iso(started + s * dt), "type": "metrics",
                      "values": values, "step": s})
    end = started + steps * dt
    meta["last_write"] = end + 0.002
    command = ["python", "train.py", "--config", f"configs/{params.get('model', 'base')}.yaml"]
    state = {"state": "running", "command": command, "pid": rng.randint(1000, 99999),
             "host": f"node-{i % 16:02d}", "started_at": iso(started), "heartbeat": iso(end),
             "heartbeat_seq": int((end - started) // HEARTBEAT_SEC),
             "heartbeat_interval_sec": HEARTBEAT_SEC}
    if status == "stuck":
        return verstr, meta, lines, state
    exit_code = 0
    if status == "succeeded":
        final = {k: _value(rng, k, 1.0) for k in keys}
        if diverge is not None:
            final[keys[0]] = values[keys[0]]
        lines.append({"timestamp": iso(end), "type": "metrics", "values": final, "step": steps})
    else:
        exc, message, exit_code = rng.choice(FAILURES)
        if exc:
            lines.append({"timestamp": iso(end), "type": "error", "exception": exc, "message": message})
    duration = round(end - started, 3)
    lines.append({"timestamp": iso(end + 0.001), "type": "run", "command": command,
                  "exit_code": exit_code, "duration_sec": duration})
    state.update(state="finished", exit_code=exit_code, finished_at=iso(end + 0.002),
                 duration_sec=duration)
    return verstr, meta, lines, state
