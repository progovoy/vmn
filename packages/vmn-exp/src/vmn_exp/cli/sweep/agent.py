"""``vmn-exp sweep agent``: claim a trial, run it like ``vmn-exp run``, repeat.

Each trial is an inner job of the sweep, created under the repo lock (it
snapshots the checkout) and supervised without it — the same split as
``vmn-exp run``. The agent stops when the sweep has no trial left, after
``--count`` trials, or when a signal ended the trial it was supervising.
"""
import copy
import json
import os
import time

from vmn_exp.cli.experiment import _experiment_create_core
from vmn_exp.cli.run import _detect_python_exe, _Supervision
from vmn_exp.core.sweep.claims import attach_run, claim_next_trial, claim_retry
from vmn_exp.core.sweep.command import trial_command
from vmn_exp.core.sweep.early_stop import MedianStopper
from vmn_exp.core.sweep.spec import SpecError
from vmn_exp.core.sweep.summary import (
    STOPPED_EARLY_TAG,
    history,
    latest_attempts,
    retryable_trials,
    trial_of,
    trial_rows,
)
from vmn_exp.core.writer import append_to_log, create_tags_entry, get_writer_id
from version_stamp.api import VMN_LOGGER


def run_agent(vcs, storage, args, sweep, spec, repo_lock=None):
    if not (getattr(args, "run_cmd", None) or spec.get("command") or spec.get("program")):
        # Checked before claiming: a claim without a run would waste its slot.
        raise SpecError("No command: give the spec a command: or program:, "
                        "or pass one after -- to sweep agent")
    if repo_lock is not None:
        repo_lock.release()  # re-taken only around each trial's creation
    agent = f"{get_writer_id()}:{os.getpid()}"
    ran = 0
    while args.count is None or ran < args.count:
        claim = _next_claim(storage, vcs.name, sweep, spec, agent, args.retry_failed)
        if claim is None:
            break
        supervision = _run_trial(vcs, storage, args, sweep, spec, claim, repo_lock)
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
    if retry_failed:
        rows = trial_rows(storage, app_name, sweep)
        latest = latest_attempts(rows)
        for trial in retryable_trials(rows):
            attempt = trial_of(latest[trial])[1] + 1
            claim = claim_retry(storage, app_name, sweep, trial, agent, attempt=attempt)
            if claim is not None:
                return claim
    return claim_next_trial(
        storage, app_name, sweep, spec, agent=agent,
        history=lambda: history(spec, trial_rows(storage, app_name, sweep)),
    )


def _run_trial(vcs, storage, args, sweep, spec, claim, repo_lock):
    trial, attempt, params = claim["trial"], claim["attempt"], claim["params"]
    command = trial_command(spec, params, override=getattr(args, "run_cmd", None))
    name = _trial_name(storage, vcs.name, sweep, trial, attempt)
    verstr = _create_trial_run(vcs, storage, args, sweep, claim, name, command, repo_lock)
    if verstr is None:
        return None
    attach_run(storage, claim, verstr)

    trial_args = copy.copy(args)
    trial_args.run_name = name
    env = {
        "VMN_SWEEP_ID": sweep,
        "VMN_SWEEP_TRIAL": str(trial),
        "VMN_SWEEP_PARAMS": json.dumps(params),
    }
    hook = _early_stop_hook(spec, storage, vcs.name, sweep, verstr)
    supervision = _Supervision(storage, vcs.name, verstr, trial_args,
                               getattr(vcs, "experiment", None), extra_env=env, on_tick=hook)
    supervision.run(command)
    return supervision


def _create_trial_run(vcs, storage, args, sweep, claim, name, command, repo_lock):
    tags = {
        "sweep": sweep,
        "sweep_trial": str(claim["trial"]),
        "sweep_attempt": str(claim["attempt"]),
    }
    if repo_lock is not None:
        repo_lock.acquire()
    try:
        verstr, err = _experiment_create_core(
            vcs, storage, parent=sweep, name=name,
            extra_create_data={"params": claim["params"], "tags": tags},
            capture_env=getattr(args, "capture_env", None),
            python_exe=_detect_python_exe(command),
        )
    finally:
        if repo_lock is not None:
            repo_lock.release()
    return None if err is not None else verstr


def _trial_name(storage, app_name, sweep, trial, attempt):
    base = (storage.load_metadata(app_name, sweep) or {}).get("name") or "sweep"
    return f"{base}-t{trial}" + (f".a{attempt}" if attempt else "")


def _early_stop_hook(spec, storage, app_name, sweep, verstr):
    """A supervision hook applying the median rule, or None without one."""
    if not spec.get("early_terminate"):
        return None
    stopper = MedianStopper(spec, storage, app_name)

    def tick(supervision):
        if supervision.stopped_early or not stopper.due(time.monotonic()):
            return
        siblings = [r["verstr"] for r in trial_rows(storage, app_name, sweep)]
        if not stopper.should_stop(verstr, siblings):
            return
        VMN_LOGGER.info(f"Sweep {sweep}: stopping {verstr} early (median rule)")
        append_to_log(storage, app_name, verstr, create_tags_entry({STOPPED_EARLY_TAG: "true"}))
        supervision.request_stop()

    return tick
