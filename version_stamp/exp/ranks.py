#!/usr/bin/env python3
"""Distributed jobs: only rank 0 records.

Under DDP/torchrun, SLURM or any launcher that starts one process per rank,
every rank runs the same training script — and so the same ``start_run()``.
Recording from each would snapshot the repo N times and produce N runs for one
job. A non-zero rank gets a :class:`NoOpRun` instead: the same interface,
recording nothing, with no heartbeat thread and no git or storage access.
"""
import os


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def process_rank(env=None):
    """This process's rank in a distributed job, or None when it is not in one.

    ``RANK`` (torchrun's global rank) is authoritative when set. Without it,
    ``LOCAL_RANK`` counts only in a job of several processes (``WORLD_SIZE >
    1``), then ``SLURM_PROCID``. Unparseable values are ignored.
    """
    env = os.environ if env is None else env
    rank = as_int(env.get("RANK"))
    if rank is not None:
        return rank
    world_size = as_int(env.get("WORLD_SIZE"))
    local_rank = as_int(env.get("LOCAL_RANK"))
    if local_rank is not None and world_size is not None and world_size > 1:
        return local_rank
    return as_int(env.get("SLURM_PROCID"))


def is_secondary_rank(env=None):
    """Whether this process is a non-zero rank, whose runs must not record."""
    rank = process_rank(env)
    return rank is not None and rank > 0


class NoOpRun:
    """What ``start_run()`` returns on a non-zero rank: records nothing.

    It is never registered as open, so ``current_run()`` stays None (autolog
    records nothing either) and ``VMN_EXPERIMENT_ID`` is not exported.
    """

    id = None

    def __init__(self, app_name=None):
        self.app_name = app_name
        self.pid = os.getpid()

    def finish(self, exit_code=0):
        return None

    def log_metric(self, key, value, step=None):
        return None

    def log_metrics(self, mapping, step=None):
        return None

    def log_params(self, mapping):
        return None

    def log_note(self, text):
        return None

    def log_artifact(self, path):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
