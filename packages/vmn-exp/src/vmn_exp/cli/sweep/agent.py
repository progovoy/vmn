"""``vmn-exp sweep agent``: claim a trial, run it like ``vmn-exp run``, repeat.

Each trial is an inner job of the sweep, created under the repo lock (it
snapshots the checkout) and supervised without it — the same split as
``vmn-exp run``. The agent stops when the sweep has no trial left, after
``--count`` trials, or when a signal ended the trial it was supervising.
"""
import copy
import json
import os
import threading
import time

from vmn_exp.cli.run import _create_experiment, _Supervision
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.background import Coalescing
from vmn_exp.core.sweep.claims import attach_run, claim_next_trial, claim_retry
from vmn_exp.core.sweep.command import require_command, trial_command
from vmn_exp.core.status import FAILED, SUCCEEDED
from vmn_exp.core.sweep.early_stop import MedianStopper
from vmn_exp.core.sweep.peer_points import PeerPoints
from vmn_exp.core.sweep.summary import history, retry_slots, trial_rows
from vmn_exp.core.writer import get_writer_id
from vmn_exp.sdk.sweep import SWEEP_PARAMS_ENV
from version_stamp.api import VMN_LOGGER

_FINISHED = (SUCCEEDED, FAILED)  # a finished trial's points never change


def run_agent(vcs, storage, args, sweep, spec, repo_lock=None):
    # Checked before claiming: a claim without a run would waste its slot.
    require_command(spec, getattr(args, "run_cmd", None))
    if repo_lock is not None:
        repo_lock.release()  # re-taken only around each trial's creation
    agent = f"{get_writer_id()}:{os.getpid()}"
    base_name = (storage.load_metadata(vcs.name, sweep) or {}).get("name") or "sweep"
    ran = 0
    while args.count is None or ran < args.count:
        claim = _next_claim(storage, vcs.name, sweep, spec, agent, args.retry_failed)
        if claim is None:
            break
        supervision = _run_trial(vcs, storage, args, sweep, spec, claim, base_name, repo_lock)
        if supervision is None:
            return 1
        ran += 1
        if supervision.forwarder.received:
            VMN_LOGGER.info(f"Sweep {sweep}: {supervision.forwarder.received} received, "
                            "agent stops")
            break
    VMN_LOGGER.info(f"Sweep {sweep}: agent ran {ran} trial(s)")
    return 0


def _next_claim(storage, app_name, sweep, spec, agent, retry_failed):
    rows = None

    def current_rows():
        nonlocal rows
        if rows is None:
            rows = trial_rows(storage, app_name, sweep, spec)
        return rows

    if retry_failed:
        for trial, attempt in retry_slots(current_rows()):
            claim = claim_retry(storage, app_name, sweep, trial, agent, attempt=attempt)
            if claim is not None:
                return claim
    return claim_next_trial(storage, app_name, sweep, spec, agent=agent,
                            history=lambda: history(spec, current_rows()))


def _run_trial(vcs, storage, args, sweep, spec, claim, base_name, repo_lock):
    trial, attempt, params = claim["trial"], claim["attempt"], claim["params"]
    trial_args = copy.copy(args)
    trial_args.run_cmd = trial_command(spec, params, override=getattr(args, "run_cmd", None))
    trial_args.run_name = f"{base_name}-t{trial}" + (f".a{attempt}" if attempt else "")
    trial_args.parent, trial_args.note, trial_args.file = sweep, None, None
    tags = {"sweep": sweep, "sweep_trial": str(trial), "sweep_attempt": str(attempt)}

    if repo_lock is not None:
        repo_lock.acquire()
    try:
        _, verstr, err = _create_experiment(
            vcs, storage, trial_args, extra_create_data={"params": params, "tags": tags}
        )
    finally:
        if repo_lock is not None:
            repo_lock.release()
    if err is not None:
        return None
    attach_run(storage, claim, verstr)

    env = {"VMN_SWEEP_ID": sweep, "VMN_SWEEP_TRIAL": str(trial),
           SWEEP_PARAMS_ENV: json.dumps(params)}
    check = _EarlyStopCheck(spec, storage, vcs.name, sweep, verstr) \
        if spec.get("early_terminate") else None
    supervision = _Supervision(storage, vcs.name, verstr, trial_args,
                               experiment_conf(vcs), extra_env=env, on_tick=check)
    try:
        supervision.run(trial_args.run_cmd)
    finally:
        if check is not None:
            check.close()
    return supervision


class _EarlyStopCheck:
    """The median rule for one trial, as a supervision hook.

    The check reads storage (the sweep's rows, the siblings' logs), so it runs
    on a background worker: the supervision loop only schedules it and acts on
    its verdict, and never waits for storage between heartbeats. Siblings'
    points are cached (:class:`PeerPoints`): a finished one is read once.
    """

    def __init__(self, spec, storage, app_name, sweep, verstr):
        self._spec = spec
        self._stopper = MedianStopper(spec)
        self._points = PeerPoints(storage, app_name, spec["metric"]["name"])
        self._storage, self._app_name = storage, app_name
        self._sweep, self._verstr = sweep, verstr
        self._verdict = threading.Event()
        self._worker = Coalescing(self._check, "vmn-sweep-early-stop")

    def __call__(self, supervision):
        if supervision.stopped_early:
            return
        if self._verdict.is_set():
            VMN_LOGGER.info(f"Sweep {self._sweep}: stopping {self._verstr} early (median rule)")
            supervision.request_stop()
        elif self._stopper.due(time.monotonic()):
            self._worker.submit()

    def close(self):
        self._worker.close(timeout=0)

    def _check(self, _item):
        # Compare the runs that carry the metric: a trial's own, or the run a
        # start_run() inside it nested under it.
        rows = trial_rows(self._storage, self._app_name, self._sweep, self._spec, wait=False)
        own_row = next((r for r in rows if r["verstr"] == self._verstr), None)
        own = self._points.of(own_row["metric_source"] if own_row else self._verstr)
        if not self._stopper.past_min_iter(own):
            return
        others = [
            self._points.of(r["metric_source"], finished=r.get("status") in _FINISHED)
            for r in rows if r["verstr"] != self._verstr
        ]
        if self._stopper.should_stop(own, others):
            self._verdict.set()
