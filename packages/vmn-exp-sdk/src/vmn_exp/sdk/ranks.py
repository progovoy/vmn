#!/usr/bin/env python3
"""Distributed jobs: only rank 0 records.

Under DDP/torchrun, SLURM or any launcher that starts one process per rank,
every rank runs the same training script — and so the same ``start_run()``.
Recording from each would snapshot the repo N times and produce N runs for one
job. A non-zero rank gets a :class:`NoOpRun` instead: the same interface,
recording nothing, with no heartbeat thread and no git or storage access.
"""
import contextlib
import os

from vmn_exp.sdk import run_repr
from vmn_exp.sdk.steps import StepCounter


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def process_rank(env):
    """This process's rank in a distributed job, or None when it is not in one.

    ``RANK`` (torchrun's global rank) is authoritative when set. Without it,
    ``LOCAL_RANK`` counts only in a job of several processes (``WORLD_SIZE >
    1``), then ``SLURM_PROCID``. Unparseable values are ignored.
    """
    rank = as_int(env.get("RANK"))
    if rank is not None:
        return rank
    world_size = as_int(env.get("WORLD_SIZE"))
    local_rank = as_int(env.get("LOCAL_RANK"))
    if local_rank is not None and world_size is not None and world_size > 1:
        return local_rank
    return as_int(env.get("SLURM_PROCID"))


def is_secondary_rank(env):
    """Whether this process is a non-zero rank, whose runs must not record."""
    rank = process_rank(env)
    return rank is not None and rank > 0


class NoOpRun:
    """What ``start_run()`` returns on a non-zero rank, or with ``disabled``
    True under ``VMN_MODE=disabled``: records nothing.

    It is never registered as open, so ``current_run()`` stays None (autolog
    records nothing either) and ``VMN_EXPERIMENT_ID`` is not exported.
    """

    id = None
    name = None
    start_step = None

    def __init__(self, app_name=None, disabled=False, rank=None, storage=None):
        self.app_name = app_name
        self.disabled = disabled
        self.rank = rank
        self._storage = storage  # start_run's storage=, read as rank 0 reads it
        self.pid = os.getpid()
        # Counted like a real run's, so `run.step` in user code works anywhere.
        self._steps = StepCounter()

    def __repr__(self):
        return run_repr.noop_text(self.app_name, self.disabled, self.rank)

    @property
    def step(self):
        return self._steps.next

    def finish(self, exit_code=0, error=None):
        return None

    def release(self, reason=None):
        return None

    def detach(self):
        return None

    def pause_background(self, timeout=None):
        return True  # no background threads

    def resume_background(self):
        return None

    @contextlib.contextmanager
    def background_paused(self, timeout=None):
        yield True

    def log_metric(self, key, value, step=None, commit=True):
        self._steps.take(step, commit)

    def log_metrics(self, mapping, step=None, commit=True):
        self._steps.take(step, commit)

    def log_params(self, mapping):
        return None

    def log_note(self, text):
        return None

    def log_artifact(self, path, name=None):
        return None

    def log_input(self, uri, name=None, digest=None, kind=None):
        return None

    def use_artifact(self, ref, path, name=None, app_name=None):
        """The artifact's local path, as rank 0 gets it — nothing is recorded:
        from ``start_run``'s ``storage=``, else where rank 0 records (in a
        checkout, the app's conf ``store:`` after the environment)."""
        from vmn_exp.sdk.run_artifacts import fetch_artifact
        from vmn_exp.sdk.store_resolve import checkout_storage

        app_name = app_name or self.app_name
        storage = self._storage or checkout_storage(app_name)
        return fetch_artifact(storage, app_name, ref, path)[2]

    def use_model(self, ref, *, storage=None):
        """The version's metadata, as rank 0 gets it — no use is recorded."""
        return self._resolved(ref, "model", storage)

    def use_dataset(self, ref, *, storage=None):
        return self._resolved(ref, "dataset", storage)

    def _resolved(self, ref, kind, storage):
        from vmn_exp.sdk.store_resolve import checkout_storage
        from vmn_exp.sdk.usage import resolved_version

        storage = storage or self._storage or checkout_storage(self.app_name)
        return resolved_version(storage, ref, kind)

    def similar(self, top=10):
        """No runs: a run that records nothing has nothing to compare."""
        return []

    def define_metric(
        self, name, step_metric=None, summary=None, goal=None, hidden=None, chart=None,
    ):
        """Records nothing; an unknown keyword fails as on a real run."""
        return None

    def _ignore(self, *args, **kwargs):
        return None

    set_tag = set_tags = remove_tag = alert = set_intent = set_progress = _ignore
    mark_range = _ignore
    log_dict = log_text = log_figure = log_artifacts = _ignore
    log_table = log_image = log_histogram = register_model = _ignore

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
