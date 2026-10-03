"""Load profiles and live-job planning for the ``vmn-exp ui`` load harness.

``plan_live`` returns JSON-serialisable job dicts (see the shared contract):
the driver hands each top-level job to a worker process, and an ``outer`` job
carries its sweep's ``inner`` jobs in ``children``.

Behaviour rules enforced here:

* process-level behaviours (``oom``/``stuck``/``recovers``) only on ``single``
  or ``outer`` jobs — every inner job of that process shares the outer's fate
  (the oracle models this through pid-level events);
* ``killed`` only on ``single`` jobs;
* an inner job is ``endless`` only under an ``endless`` outer (otherwise the
  outer could never finish).

An ``outer`` job's ``steps``/``fail_at_step``/``stop_at_step`` refer to the
outer's own logging loop; how it interleaves with its children is the
worker's choice. ``endless`` jobs treat ``steps`` as one cycle and keep
logging until teardown. ``metric_keys`` never contains ``probe_ts``: every
worker logs it on every step on top of these keys.
"""
import dataclasses
import math
import random

from vmn_exp.core.status import STALE_MULTIPLIER

BEHAVIORS = (
    "succeed", "crash", "oom", "stuck", "recovers",
    "killed", "chatty", "wide", "endless",
)
PROCESS_LEVEL = frozenset({"oom", "stuck", "recovers"})
INNER_BEHAVIORS = ("succeed", "crash", "chatty", "wide", "endless")

_WEIGHTS = {
    "succeed": 40, "crash": 10, "oom": 5, "stuck": 5, "recovers": 5,
    "killed": 5, "chatty": 10, "wide": 5, "endless": 15,
}
_BASE_METRICS = ["loss", "acc", "val_loss", "val_acc"]
_CHATTY_SLEEP_SEC = 0.01
_STEP_SLEEPS = (0.05, 0.1, 0.2)


@dataclasses.dataclass(frozen=True)
class Profile:
    name: str
    seeded_runs: int
    seeded_sweeps: int
    seeded_inner_per_sweep: int
    live_jobs: int  # concurrent top-level jobs (worker processes)
    live_sweeps: int
    live_inner_per_sweep: int
    duration_sec: float  # 0 = until Ctrl-C
    heartbeat_sec: float
    min_stale_sec: float
    max_metric_keys: int
    max_steps: int
    max_params: int
    behavior_weights: dict
    probe_concurrency: int

    @property
    def stale_sec(self):
        """Heartbeat age past which the UI reports a run as stuck."""
        return max(STALE_MULTIPLIER * self.heartbeat_sec, self.min_stale_sec)


PROFILES = {
    p.name: p
    for p in (
        Profile("smoke", 500, 5, 10, 30, 2, 5, 45, 1, 5, 20, 2000, 20, _WEIGHTS, 4),
        Profile("load", 100_000, 200, 50, 500, 20, 20, 300, 2, 8, 50, 5000, 30,
                _WEIGHTS, 16),
        Profile("soak", 250_000, 500, 50, 2000, 50, 20, 0, 2, 10, 50, 5000, 30,
                _WEIGHTS, 32),
    )
}


def get_profile(name):
    return PROFILES[name]


@dataclasses.dataclass(frozen=True)
class SeriesProfile:
    """A static (no live jobs) metric-volume profile (plan 12 §10 4b): *big*
    runs with long series, *wide* runs with many keys, and *overlay* runs a
    comparison chart overlays one key of. Seeded by :mod:`uiload.seed_series`
    and measured by :mod:`uiload.probe_series` against ``slo.SERIES_BUDGETS``."""
    name: str
    big_runs: int
    big_steps: int
    big_keys: int
    wide_runs: int
    wide_steps: int
    wide_keys: int
    overlay_runs: int
    overlay_steps: int
    series_points: int  # max_points of a series / zoom request
    probe_requests: int  # requests per measured route

    @property
    def seeded_runs(self):
        return self.big_runs + self.wide_runs + self.overlay_runs


SERIES_PROFILES = {
    p.name: p
    for p in (
        SeriesProfile("bigseries", 50, 1_000_000, 50, 1, 10_000, 5000, 1000, 10_000, 2000, 200),
        SeriesProfile("bigseries-tiny", 2, 5000, 4, 1, 50, 300, 30, 100, 2000, 10),
    )
}


def get_series_profile(name):
    return SERIES_PROFILES[name]


def flatten(jobs):
    """Yield every job, each outer followed by its nested children."""
    for job in jobs:
        yield job
        yield from flatten(job["children"])


def plan_live(profile, rng_seed, start_index=0, count=None):
    """Plan ``count`` top-level live jobs (default ``profile.live_jobs``).

    Job ids are ``live-NNNNNN`` numbered from ``start_index`` across outer and
    inner jobs alike, so the next replacement batch starts at
    ``start_index + len(list(flatten(jobs)))``. Sweeps are spread in
    proportion ``live_sweeps / live_jobs``. Deterministic per
    ``(rng_seed, start_index)``.
    """
    count = profile.live_jobs if count is None else count
    rng = random.Random(f"{rng_seed}:{start_index}")
    n_sweeps = round(count * profile.live_sweeps / profile.live_jobs)
    sweep_slots = set(rng.sample(range(count), n_sweeps))
    jobs, next_index = [], start_index
    for slot in range(count):
        kind = "outer" if slot in sweep_slots else "single"
        job = _plan_job(profile, rng, next_index, kind, None, None)
        next_index += 1
        if kind == "outer":
            for _ in range(profile.live_inner_per_sweep):
                child = _plan_job(profile, rng, next_index, "inner",
                                  job["job_id"], job["behavior"])
                job["children"].append(child)
                next_index += 1
        jobs.append(job)
    return jobs


def _allowed_behaviors(kind, outer_behavior):
    if kind == "single":
        return BEHAVIORS
    if kind == "outer":
        return tuple(b for b in BEHAVIORS if b != "killed")
    if outer_behavior == "endless":
        return INNER_BEHAVIORS
    return tuple(b for b in INNER_BEHAVIORS if b != "endless")


def _plan_job(profile, rng, index, kind, parent_job, outer_behavior):
    choices = _allowed_behaviors(kind, outer_behavior)
    weights = [profile.behavior_weights[b] for b in choices]
    behavior = rng.choices(choices, weights)[0]
    wide = behavior == "wide"
    steps, step_sleep = _timing(profile, rng, behavior)
    job = {
        "job_id": f"live-{index:06d}",
        "behavior": behavior,
        "kind": kind,
        "parent_job": parent_job,
        "params": _params(rng, rng.randint(50, 80) if wide
                          else rng.randint(7, profile.max_params)),
        "tags": {"behavior": behavior, "kind": kind, "uiload": "live",
                 "team": rng.choice(["vision", "nlp", "rl", "infra"])},
        "metric_keys": _metric_keys(rng.randint(300, 1000) if wide
                                    else rng.randint(4, profile.max_metric_keys)),
        "steps": steps,
        "step_sleep_sec": step_sleep,
        "fail_at_step": None,
        "stop_at_step": None,
        "resume_after_sec": None,
        "kill_after_sec": None,
        "children": [],
    }
    _set_fate(job, profile, rng)
    return job


def _lifetime_range(profile):
    base = profile.duration_sec or 300
    lo = max(5.0, base / 9)
    return lo, max(lo, base * 2 / 3)


def _timing(profile, rng, behavior):
    """Return ``(steps, step_sleep_sec)`` for a lifetime within the profile."""
    life = rng.uniform(*_lifetime_range(profile))
    if behavior == "chatty":
        steps = min(profile.max_steps, math.ceil(life / _CHATTY_SLEEP_SEC))
        return steps, _CHATTY_SLEEP_SEC
    steps = max(4, min(profile.max_steps, int(life / rng.choice(_STEP_SLEEPS))))
    return steps, life / steps


def _set_fate(job, profile, rng):
    steps, behavior = job["steps"], job["behavior"]
    mid_step = rng.randint(max(1, steps // 4), max(1, 3 * steps // 4))
    if behavior in ("crash", "oom"):
        job["fail_at_step"] = mid_step
    elif behavior in ("stuck", "recovers"):
        job["stop_at_step"] = mid_step
    if behavior == "recovers":
        job["resume_after_sec"] = round(profile.stale_sec * rng.uniform(1.5, 2.5) + 2, 2)
    elif behavior == "killed":
        life = steps * job["step_sleep_sec"]
        job["kill_after_sec"] = round(life * rng.uniform(0.25, 0.75), 2)


def _params(rng, n):
    params = {
        "lr": float(f"{10 ** rng.uniform(-5, -1):.3g}"),
        "batch_size": rng.choice([16, 32, 64, 128, 256]),
        "optimizer": rng.choice(["adam", "adamw", "sgd", "rmsprop"]),
        "use_amp": rng.random() < 0.5,
        "dropout": round(rng.uniform(0.0, 0.5), 2),
        "seed": rng.randint(0, 2**31 - 1),
        "model": rng.choice(["resnet50", "vit_b16", "bert_base", "mlp"]),
    }
    for i in range(n - len(params)):
        params[f"hp_{i:03d}"] = round(rng.uniform(0, 1), 4)
    return params


def _metric_keys(n):
    extra = [f"grad_norm_l{i:03d}" for i in range(n - len(_BASE_METRICS))]
    return _BASE_METRICS + extra
