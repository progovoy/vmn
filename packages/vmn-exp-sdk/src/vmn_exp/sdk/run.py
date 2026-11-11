#!/usr/bin/env python3
"""The in-process experiment SDK: ``start_run()`` and the ``Run`` it returns.

``vmn-exp run`` supervises a child process and records what happened to it. That
is the wrong shape for a training script, which wants to record metrics from
*inside* the loop. ``start_run()`` is the same recorder, hosted by the workload
itself.

Records are deliberately identical to the CLI's: the verstr allocation, the
``metadata.yml``, the per-writer JSONL log and the ``run_state.yml`` schema all
come from the same helpers ``vmn-exp run`` uses, so ``vmn-exp list/show`` and the
dashboard read an SDK run with no special cases.
"""
import atexit
import functools
import logging
import os
import signal
import socket
import sys
import threading
import time

from vmn_exp._base import ensure_logger, now_iso
from vmn_exp.core.best_effort import BestEffort, quiet
from vmn_exp.core.intent import build_intent_entry
from vmn_exp.core.metric_compact import compact_by
from vmn_exp.core.rerun import RUNNER_SDK, repo_relative_cwd
from vmn_exp.core.run_error import error_from_exception
from vmn_exp.core.run_intervals import (
    DEFAULT_SYNC_INTERVAL_SEC,
    resolve_heartbeat_sec,
    resolve_sync_sec,
)
from vmn_exp.core.state_cas import new_attempt_id
from vmn_exp.core.status import positive_env_sec
from vmn_exp.core.storage_resolve import try_repo_root
from vmn_exp.core.values import sanitize_entry
from vmn_exp.core.writer import (
    append_entries_to_log,
    split_for_append,
    stamped_entry,
    sync_to_remote,
)
from vmn_exp.sdk import (
    _resolve_app_name,  # noqa: F401  (one shared resolver)
    context,
    fork,
    release,
    resume,
    signals,
    sysmetrics,
)
from vmn_exp.sdk.context import (  # noqa: F401  (re-exported API)
    _OPEN_RUNS,
    EXPERIMENT_ID_ENV,
    current_run,
    owner_only,
)
from vmn_exp.sdk.create import SNAPSHOT_METADATA_ENV, create_record  # noqa: F401
from vmn_exp.sdk import fork_safety  # noqa: F401  (registers the fork handlers)
from vmn_exp.sdk.background_gate import BackgroundGate, RunBackground
from vmn_exp.sdk.exit_code import ExitCodeNote
from vmn_exp.sdk.heartbeat import Heartbeat
from vmn_exp.sdk.log_buffer import LogBuffer
from vmn_exp.sdk.log_sync import LogSync
from vmn_exp.sdk.metric_defs import MetricDefinitions
from vmn_exp.sdk.mode import is_disabled
from vmn_exp.sdk.output_capture import RunOutput
from vmn_exp.sdk.process_hooks import ProcessHooks
from vmn_exp.sdk import run_repr
from vmn_exp.sdk.ranks import NoOpRun, is_secondary_rank, process_rank
from vmn_exp.sdk.run_alerts import RunAlerts
from vmn_exp.sdk.run_artifacts import RunArtifacts
from vmn_exp.sdk.run_close import RunClose
from vmn_exp.storage.ship_state import finalizing
from vmn_exp.sdk.media_uploads import MediaUploads
from vmn_exp.sdk.run_media import RunMedia
from vmn_exp.sdk.run_metrics import RunMetrics
from vmn_exp.sdk.run_records import RunRecords
from vmn_exp.sdk.state_publisher import RunStatePublisher
from vmn_exp.sdk.steps import StepCounter, first_step

# Stdlib logging, not VMN_LOGGER: an SDK user never calls init_stamp_logger, and
# a library emits records rather than configuring handlers.
_LOGGER = logging.getLogger(__name__)

# start_run()'s sync_interval_sec when not given: env > conf > 30 decide.
_SYNC_UNSET = object()
# How long finish() waits for the last remote writes before giving up on them,
# unless FINAL_UPLOAD_TIMEOUT_ENV overrides it.
FINAL_REMOTE_TIMEOUT_SEC = 60
FINAL_UPLOAD_TIMEOUT_ENV = "VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC"
# The same wait under SIGTERM, unless FINAL_UPLOAD_TIMEOUT_ENV overrides it:
# it fits a Kubernetes pod's default 30 s grace period.
SIGTERM_FINAL_TIMEOUT_SEC = 25
# Under SIGTERM media files get at most this share of what is left, so the
# final state is written with budget to spare.
SIGTERM_MEDIA_SHARE = 0.5

# A run that reached interpreter exit still open was abandoned. Most of the
# time that is just an mlflow-style "forgot to call finish()" — the process
# fell off the end cleanly — and must read as succeeded, like the workload's
# own exit code says. An uncaught exception (see ``_note_uncaught_exception``
# below) makes it read as failed with this code instead, and ``sys.exit(N)``
# (noted by ``_EXIT_NOTE``) with N.
ABANDONED_EXIT_CODE = 1

# The uncaught exception that reached the top of this process, if any,
# recorded as the abandoned runs' ``error``. ``SystemExit`` never reaches
# ``sys.excepthook`` (CPython special-cases it before running atexit
# handlers); ``_EXIT_NOTE`` wraps ``sys.exit`` for that. Both hooks are
# installed at the first run open (``_install_process_hooks``), not on import.
_uncaught_exception = None
_EXIT_NOTE = ExitCodeNote()
# A Run built without ``install_hooks`` installs this process's real hooks.
_PROCESS_HOOKS_DEFAULT = object()


def _note_uncaught_exception(exc_value):
    global _uncaught_exception
    _uncaught_exception = exc_value


def start_run(
    app_name=None,
    *,
    note=None,
    params=None,
    parent=None,
    nested=False,
    heartbeat_interval_sec=None,
    storage=None,
    system_metrics=None,
    sync_interval_sec=_SYNC_UNSET,
    run_id=None,
    all_ranks=False,
    name=None,
    tags=None,
    capture_env=None,
    fork_from=None,
    fork_step=None,
    rewind_to_step=None,
    capture_output=False,
    mode=None,
    intent=None,
    intent_keywords=None,
    on_sigterm=None,
    sigterm_exit=None,
    reopen=False,
    export_env=True,
    code=None,
):
    """Create an experiment (or reopen one), mark it running and return the ``Run``.

    ``app_name=None`` resolves the app from the current checkout. Every other
    argument is keyword-only. Use the result as a context manager, or call
    ``finish()`` yourself.

    With ``VMN_SNAPSHOT_METADATA`` set (a container built from ``vmn-exp
    export``) no git checkout is needed: the run records against that snapshot
    into ``VMN_EXPERIMENT_DIR`` (or *storage*), exactly like the CLI.

    ``code=False`` (or ``VMN_EXP_CODE=none`` when *code* is not given) records
    no code at all — a notebook or a scratch directory: the app must be named
    (*app_name* or ``VMN_APP_NAME``) and the store given as above. The run is
    ``0.0.0-nocode[.rN]`` and is never rerun, restored or diffed. Never a
    fallback: without it, a directory outside a checkout is an error.

    System metrics — this process's CPU and memory (and GPU, with ``pynvml``) —
    are recorded as ``sys_*`` metrics on every heartbeat unless opted out:
    ``system_metrics=False`` > ``VMN_SYSTEM_METRICS=0`` > conf
    ``experiment.system_metrics: false``. ``True`` overrides only the conf.
    Inside a ``vmn-exp run`` that samples its child's tree they default off
    (that supervisor already measures this process); ``True`` samples anyway.

    ``sync_interval_sec`` pushes the log to a remote store (when *storage* has
    one) at most that often, off the heartbeat thread. ``None``/``0`` syncs only
    on ``finish()``. Not given, it and ``heartbeat_interval_sec`` come from
    ``VMN_EXP_SYNC_SEC`` / ``VMN_EXP_HEARTBEAT_SEC``, else conf
    ``experiment.sync_interval_sec`` / ``experiment.heartbeat_interval_sec``,
    else 30.

    ``name`` is a human-readable run name, stored in ``metadata.yml`` and shown
    by ``vmn-exp list``; ``tags`` (``{key: value}``) are set once the run opens.

    ``run_id`` (or ``VMN_RESUME_RUN_ID``) reopens an existing run of the app
    instead of creating one — a requeued job continuing where it was preempted.
    A finished run is refused (ValueError) unless ``reopen=True`` (or
    ``VMN_RESUME_REOPEN=1`` with the env var): reopening clears its exit code.
    With ``rewind_to_step=N`` too, the reopened run's history past step N is
    hidden (refused while the run is live elsewhere).

    =========================  ===========================================
    ``start_run(run_id=X)``    takes the existing run X (ValueError if none)
    ``create_run(run_id=X)``   registers a new run named exactly X
    ``name=``                  a display label; never looked up
    =========================  ===========================================

    ``fork_from`` (a run ref, optionally ``"<ref>?_step=N"``) with
    ``fork_step=N`` creates a NEW run that starts with that run's metrics and
    params up to step N (all of them without a step) and continues from N + 1;
    ``run.start_step`` is the step to log next.

    On a non-zero rank of a distributed job (``RANK``, ``LOCAL_RANK`` with
    ``WORLD_SIZE > 1``, or ``SLURM_PROCID``) this returns a :class:`NoOpRun`
    that records nothing, unless ``all_ranks=True``.

    ``capture_output=True`` tees this process's stdout/stderr (fds 1 and 2, so
    subprocesses and C extensions too) into the run's ``output.log`` artifact,
    capped by ``VMN_EXP_OUTPUT_CAP_MB`` (default 10), uploaded every
    ``sync_interval_sec`` and at finish. Off by default: the process then
    writes to pipes, not its TTY.

    In the command ``vmn-exp run`` started itself (its direct child), a call
    naming no *parent*, *nested* or *fork_from* records into the supervisor's
    run, in a stream of its own (:mod:`vmn_exp.sdk.guest_run`), unless
    ``--no-adopt`` / ``VMN_EXP_ADOPT=0`` turned the offer off.

    ``mode="disabled"`` (or ``VMN_MODE=disabled``; an explicit *mode* wins)
    returns a :class:`NoOpRun` without touching git or the store.

    ``intent`` (with ``intent_keywords``) says what the run is for, as with
    :meth:`Run.set_intent` once the run opens — a resumed run gets one only
    when given. A bad one raises ValueError before anything is created.

    ``on_sigterm`` is what the SDK's SIGTERM handler does with the run:
    ``"fail"`` finishes it with exit code 143; ``"release"`` hands it back
    unfinished (:meth:`Run.release`) for a retry to reopen with ``run_id=``.
    Not given, it is ``VMN_EXP_ON_SIGTERM``, else ``"fail"``. ``sigterm_exit``
    is what the handler does next: ``"kill"`` re-delivers the signal so the
    process dies of it; ``"raise"`` raises ``SystemExit(143)`` in the main
    thread so ``finally`` blocks run. Not given, ``VMN_EXP_SIGTERM_EXIT``,
    else ``"kill"``. Either raises ValueError before anything is created.

    ``export_env=False`` keeps the run out of ``os.environ``: it is still the
    calling context's current run (heartbeat, atexit, nesting), but neither
    opening nor closing it sets or restores ``VMN_EXPERIMENT_ID`` /
    ``VMN_APP_NAME`` — for orchestrators opening runs from worker threads,
    where the process-shared env would leak one run's ID into a sibling.
    Subprocesses then do not nest under it unless given the ID themselves.
    """
    on_sigterm = release.resolve_on_sigterm(on_sigterm)
    sigterm_exit = release.resolve_sigterm_exit(sigterm_exit)
    if is_disabled(mode):
        return NoOpRun(app_name, disabled=True)
    if not all_ranks and is_secondary_rank():
        return NoOpRun(app_name, rank=process_rank())
    # The reused CLI helpers log through VMN_LOGGER, which raises until something
    # initializes it — and a library must not call init_stamp_logger.
    ensure_logger()
    _check_intent(intent, intent_keywords)

    prior_state, start_step = None, None
    ref, reopen = resume.requested_run_id(run_id, reopen)
    fork.check_modes(ref, fork_from, rewind_to_step)
    adopted = None if ref else _adopted_record(app_name, storage, parent, nested, fork_from)
    if ref:
        # Resume: locate the existing run; env stays as originally captured.
        app_name, storage, verstr, prior_state, exp_conf = resume.locate(
            app_name, ref, storage, from_env=not run_id
        )
        resume.check_reopenable(app_name, verstr, prior_state, reopen, not run_id)
        if rewind_to_step is not None:
            start_step = fork.rewind(storage, app_name, verstr, prior_state, rewind_to_step)
    elif adopted:
        app_name, storage, verstr, exp_conf = adopted
    else:
        if fork_from:
            app_name, storage, source, fork_step = fork.locate_source(
                app_name, fork_from, fork_step, storage
            )
        app_name, storage, verstr, exp_conf = create_record(
            app_name, note, params, parent, nested, storage, name,
            capture_env=capture_env, code=code,
        )
        if fork_from:
            start_step = fork.seed(storage, app_name, verstr, source, fork_step)

    run = _run_class(adopted)(
        storage,
        app_name,
        verstr,
        resolve_heartbeat_sec(heartbeat_interval_sec, exp_conf),
        system_metrics=sysmetrics.sdk_enabled(system_metrics, exp_conf),
        sync_interval_sec=resolve_sync_sec(
            None if sync_interval_sec is _SYNC_UNSET else sync_interval_sec or 0,
            exp_conf,
        ),
        prior_state=prior_state,
        name=name,
        capture_output=capture_output,
        exp_conf=exp_conf,
        on_sigterm=on_sigterm,
        sigterm_exit=sigterm_exit,
        export_env=export_env,
        install_hooks=_real_process_hooks(),
    )
    run.start_step = start_step
    run._steps = StepCounter(
        first_step(storage, app_name, verstr, start_step, prior_state is not None)
    )
    run._open()
    if prior_state is not None or adopted:
        _record_resume_inputs(run, note, params)
    if tags:
        run.set_tags(tags)
    if intent is not None:
        run.set_intent(intent, keywords=intent_keywords)
    return run


def _adopted_record(app_name, storage, parent, nested, fork_from):
    """The record of the run ``vmn-exp run`` offers this process, when it
    takes it (:mod:`vmn_exp.sdk.guest_run`); None otherwise."""
    from vmn_exp.sdk.guest_run import adopted_record

    return adopted_record(app_name, storage, parent, nested, fork_from,
                          context.context_run(), os.environ, os.getppid, resume.locate)


def _run_class(adopted):
    if not adopted:
        return Run
    from vmn_exp.sdk.guest_run import GuestRun

    return GuestRun


def _check_intent(intent, keywords):
    if intent is not None:
        build_intent_entry(intent, keywords)
    elif keywords is not None:
        raise ValueError("intent_keywords needs an intent")


def _record_resume_inputs(run, note, params):
    """A resumed or adopted run's new note/params are appended, like any
    later entry."""
    if params:
        run.log_params(params)
    if note:
        run.log_note(note)


def _checkout_relative_cwd():
    """This process's cwd relative to its checkout; None when git-free."""
    if os.environ.get(SNAPSHOT_METADATA_ENV):
        return None
    return repo_relative_cwd(os.getcwd(), try_repo_root())


class Run(RunMetrics, MetricDefinitions, RunArtifacts, RunMedia, RunAlerts, RunBackground,
          RunRecords, RunClose):
    """One open experiment run: a metrics sink plus a liveness publisher."""

    disabled = False

    def __init__(
        self,
        storage,
        app_name,
        verstr,
        heartbeat_interval_sec,
        system_metrics=False,
        sync_interval_sec=DEFAULT_SYNC_INTERVAL_SEC,
        prior_state=None,
        name=None,
        capture_output=False,
        exp_conf=None,
        on_sigterm=release.FAIL,
        sigterm_exit=release.KILL,
        export_env=True,
        install_hooks=_PROCESS_HOOKS_DEFAULT,
        writer=None,
    ):
        self._storage = storage
        # The writer id of this run's own streams; None: the process's.
        self._writer = writer
        # Installs the process's excepthook and atexit finalizer at open;
        # left out, the real ones; None installs none.
        if install_hooks is _PROCESS_HOOKS_DEFAULT:
            install_hooks = _real_process_hooks()
        self._install_hooks = install_hooks
        self._export_env = export_env
        self._on_sigterm = on_sigterm
        self._sigterm_exit = sigterm_exit
        # The checkout's `experiment:` conf, as start_run() read it.
        self._exp_conf = exp_conf
        self.app_name = app_name
        self.id = verstr
        self.name = name
        # The step a fork or a rewound run continues from (None otherwise).
        self.start_step = None
        # The step a log_metrics() without step= records; start_run() seeds it.
        self._steps = StepCounter()
        self._progress_unit = None  # the last set_progress() unit logged
        # The process that owns the run. A forked child inherits this object but
        # not the run: `current_run()` there is None, atexit leaves it alone and
        # every recording or closing call on it is dropped (_in_owner).
        self.pid = os.getpid()
        self._inert_warned_pid = None

        self._finished = False
        self._detached = False
        self._monotonic_start = time.monotonic()
        self._sync_interval_sec = sync_interval_sec
        self._last_sync = self._monotonic_start
        self._ctx_prev = None

        self._state = self._initial_state(heartbeat_interval_sec, prior_state)
        # A resumed run's duration spans every attempt, from the first start.
        self._elapsed_before = (
            resume.elapsed_before(self._state) if prior_state is not None else 0.0
        )
        # Every background storage call goes through it: pause_background()
        # and the fork handlers (fork_safety) hold them all.
        self._gate = BackgroundGate()
        self._state_publisher = RunStatePublisher(
            storage, app_name, verstr, self._gate, resumes=prior_state,
            abandon=threading.Event())
        self._refused_warned = False
        self._log_buffer = LogBuffer(
            functools.partial(append_entries_to_log, storage, app_name, verstr, writer=writer),
            self._gate,
            split=split_for_append,
            on_refused=self._warn_refused_once,
        )
        self._chore_guard = quiet(_LOGGER)
        self._log_sync = LogSync(self._sync_log, self._gate, threading.Event())
        self._heartbeat = Heartbeat(self._gate.wrap(self._beat), heartbeat_interval_sec)
        self._media_uploads = MediaUploads(self._gate.wrap(self._save_artifact_file))
        self._output = (
            RunOutput(storage, app_name, verstr, self._gate) if capture_output else None
        )
        # No pid: this process *is* the workload.
        self._sampler = sysmetrics.Sampler(self._log_unstepped, system_metrics)
        # Recording the run's outcome warns once per step; heartbeat chores and
        # syncs are routine enough to stay at debug.
        self._record_guard = BestEffort(
            _LOGGER,
            lambda what, exc: f"vmn: could not record the {what} of run {self.id}: {exc}",
        )

    @staticmethod
    def _initial_state(heartbeat_interval_sec, prior_state):
        started_at = now_iso()
        state = {
            "state": "running",
            # There is no child command here — the run *is* this process. Its
            # argv is the honest answer, and consumers read the key.
            "command": list(sys.argv),
            "runner": RUNNER_SDK,
            "cwd": _checkout_relative_cwd(),
            "pid": os.getpid(),
            "host": socket.gethostname(),
            # This process's attempt at the run: a duplicate attempt's
            # heartbeats never reopen a run another attempt finished.
            "attempt": new_attempt_id(),
            "started_at": started_at,
            "heartbeat": started_at,
            # Bumped every beat: a liveness signal that needs no clock.
            "heartbeat_seq": 0,
            "heartbeat_interval_sec": heartbeat_interval_sec,
            "exit_code": None,
            "finished_at": None,
            "duration_sec": None,
        }
        if prior_state is not None:
            state = resume.resumed_state(prior_state, state)
        return state

    # -- lifecycle ---------------------------------------------------------

    def _open(self):
        if self._install_hooks is not None:
            self._install_hooks()
        self._publish()
        context.register(self)
        self._defer_ships()
        install_signal_handlers()
        if self._output is not None:
            self._chore_guard("output capture", self._output.start)
        self._heartbeat.start()

    def __repr__(self):
        return run_repr.text(*self._repr_fields())

    def _repr_html_(self):
        return run_repr.html(*self._repr_fields())

    def _repr_fields(self):
        state = self._state
        return self.app_name, self.id, self.name, state.get("state"), state.get("exit_code")

    def _defer_ships(self):
        """Due ships of a direct-to-bucket storage go to the run's sync
        worker, never the appending thread (a heartbeat, a log_metric call)."""
        defer = getattr(self._storage, "defer_ships", None)
        if defer is not None:
            defer(self.app_name, self.id, self._log_sync.submit)

    def _undefer_ships(self):
        undefer = getattr(self._storage, "undefer_ships", None)
        if undefer is not None:
            undefer(self.app_name, self.id)

    def _sync_log(self):
        # sync_to_remote is looked up here, at call time: tests patch it on
        # this module.
        sync_to_remote(self._storage, self.app_name, self.id, **self._writer_arg())

    def _writer_arg(self):
        """``writer=`` for a run with a writer of its own; nothing otherwise."""
        return {} if self._writer is None else {"writer": self._writer}

    def _remote_writers(self):
        writers = [("log", self._log_sync), ("state", self._state_publisher)]
        if self._output is not None:
            writers.append(("output log", self._output))
        return writers

    def _duration(self):
        return round(self._elapsed_before + time.monotonic() - self._monotonic_start, 3)

    # The close path (run_close) reaches these through the instance: tests
    # patch compact_by, error_from_exception and FINAL_REMOTE_TIMEOUT_SEC on
    # this module, so the names are looked up here, at call time.

    def _compact_by(self, *args):
        compact_by(*args)

    def _error_from_exception(self, error):
        return error_from_exception(error)

    @staticmethod
    def _final_deadline():
        return _final_upload_deadline()

    @staticmethod
    def _time_left(deadline):
        return _left(deadline)

    # -- recording ---------------------------------------------------------

    @owner_only()
    def set_intent(self, text, keywords=None, generator=None):
        """Say what this run is for: markdown *text* (cut at 16 KiB),
        *keywords* (synonyms, the problem's usual names) and the *generator*
        (model id) that wrote it, if any. Matched by similar-run search; the
        latest intent wins, also on a finished run — nothing ships its log
        any more, so the entry is synced to the remote at once."""
        self._append(stamped_entry(build_intent_entry(text, keywords, generator)))
        if self._finished and not self._detached:
            self._record_guard("intent", sync_to_remote, self._storage, self.app_name,
                               self.id, **self._writer_arg())

    # -- internals ---------------------------------------------------------

    def _after_fork_in_child(self):
        # The child has none of this run's threads (and is not its writer).
        self._gate.after_fork_in_child()
        self._log_buffer.after_fork_in_child()

    def _in_owner(self):
        """Whether this process opened the run; in a forked child it did not,
        and the call is dropped (warned once per run per process)."""
        here = os.getpid()
        if here == self.pid:
            return True
        if self._inert_warned_pid != here:
            self._inert_warned_pid = here
            _LOGGER.warning(f"vmn: run {self.id} was opened by pid {self.pid}; "
                            "in a forked worker call start_run() to record")
        return False

    @owner_only()
    def _append(self, entry):
        entry = sanitize_entry(entry)
        if entry is not None:
            self._log_buffer.append(entry)

    def _warn_refused_once(self, count):
        if self._refused_warned:
            return
        self._refused_warned = True
        _LOGGER.warning(f"vmn: run {self.id} no longer exists in the store; "
                        f"{count} entries were not recorded")

    def _publish(self, updates=(), final=False):
        self._state.update(updates)
        self._state_publisher.publish(self._state, final=final)

    def _beat(self):
        # Independent chores: a failed heartbeat write must not skip the sync
        # that would get the log off this box, nor the other way round.
        chores = (
            self._publish_heartbeat,
            self._sampler.tick,
            self._log_buffer.flush,
            self._maybe_sync,
        )
        for chore in chores:
            self._chore_guard(f"heartbeat chore {chore.__name__}", chore)

    def _publish_heartbeat(self):
        self._state.update(
            heartbeat=now_iso(), heartbeat_seq=self._state["heartbeat_seq"] + 1
        )
        self._state_publisher.publish(self._state, heartbeat=True)

    def _maybe_sync(self):
        if not self._sync_interval_sec:
            return
        if time.monotonic() - self._last_sync < self._sync_interval_sec:
            return
        self._last_sync = time.monotonic()
        self._log_sync.submit()
        if self._output is not None:
            self._output.request_upload()


def _finalize_open_runs(exit_code=None, deadline=None, media_share=1.0, exit_note=None,
                        **final_state):
    """Never leave a run claiming ``running`` just because nobody finished it.

    With no explicit *exit_code* (the atexit case) a clean process exit reads
    as succeeded; a genuinely uncaught exception reads as failed (see
    ``_uncaught_exception``), else the code *exit_note* noted from
    ``sys.exit(N)``. ``_finalize_signaled`` always passes an explicit code, so
    a killed process is unaffected.

    Only this process's runs: a forked child exiting normally must not finalize
    — and so mark failed — the parent's still-running run. A run opened with
    ``on_sigterm="release"`` is released instead when a signal ended it
    (``final_state["signal"]``).

    *deadline* defaults to the final-upload timeout from now; *media_share* is
    the share of it each run's media files may wait for (see ``_close_attempt``).
    """
    error = None
    if exit_code is None:
        exit_code, error = _abandoned_exit(exit_note)
    # One shared deadline for every run's uploads: a hung remote must not
    # spend the whole budget on each run in turn. Media files are waited for
    # while recording (their entries must precede the final flush); the rest
    # of the uploads after every run's final state is written.
    if deadline is None:
        deadline = _final_upload_deadline()
    recorded = [
        run
        for run in reversed(context.open_runs())
        if _quietly(_end_attempt, run, deadline, media_share, exit_code, error, final_state)
    ]
    for run in recorded:
        _quietly(run._close_remote_writers, deadline)


def _abandoned_exit(exit_note):
    """The exit code and error of runs still open at a process exit."""
    if _uncaught_exception is not None:
        return ABANDONED_EXIT_CODE, _uncaught_exception
    return (0 if exit_note is None else exit_note.noted()), None


def _end_attempt(run, deadline, media_share, exit_code, error, final_state):
    if final_state.get("signal") and run._on_sigterm == release.RELEASE:
        return run._record_release(
            deadline, signal=final_state["signal"], media_share=media_share)
    return run._record_final(
        exit_code, deadline, error=error, media_share=media_share, **final_state)


def _quietly(step, *args, **kwargs):
    try:
        return step(*args, **kwargs)
    except Exception:
        _LOGGER.debug("Failed to finalize an abandoned run", exc_info=True)
        return False


def final_upload_timeout_sec():
    """How long finalizing waits for the last uploads: ``VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC``
    when a positive number, else a minute. Read when a run is finalized."""
    return positive_env_sec(FINAL_UPLOAD_TIMEOUT_ENV, FINAL_REMOTE_TIMEOUT_SEC)


def sigterm_timeout_sec():
    """How long finalizing under SIGTERM waits: ``VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC``
    when a positive number, else 25 s (or the final-upload default, if lower)."""
    timeout = positive_env_sec(FINAL_UPLOAD_TIMEOUT_ENV, None)
    if timeout is None:
        return min(FINAL_REMOTE_TIMEOUT_SEC, SIGTERM_FINAL_TIMEOUT_SEC)
    return timeout


def _final_upload_deadline(timeout_sec=None):
    """The deadline *timeout_sec* (default: the final-upload timeout) from now."""
    if timeout_sec is None:
        timeout_sec = final_upload_timeout_sec()
    return time.monotonic() + timeout_sec


def _left(deadline):
    return max(0.0, deadline - time.monotonic())


def _finalize_signaled(signum):
    """A run a signal ended exits ``128 + N``, as a shell reports it — or is
    released, when it was opened with ``on_sigterm="release"``."""
    name = signal.Signals(signum).name
    deadline = _final_upload_deadline(sigterm_timeout_sec())
    with finalizing():
        _finalize_open_runs(128 + signum, deadline=deadline, media_share=SIGTERM_MEDIA_SHARE,
                            received_signal=name, signal=name)


def install_signal_handlers():
    """Finalize open runs on SIGTERM. Call from the main thread.

    Done already when ``vmn_exp.sdk`` is imported on the main thread; call it
    again after installing a SIGTERM handler of your own (it is chained), or
    when the SDK is first imported from a worker thread.
    """
    signals.install(_finalize_signaled, timeout=sigterm_timeout_sec,
                    raises=_sigterm_raises, has_work=_has_open_runs)


def _sigterm_raises():
    """Whether an open run asked for ``sigterm_exit="raise"``."""
    return any(run._sigterm_exit == release.RAISE for run in context.open_runs())


def _has_open_runs():
    return bool(context.open_runs())


def _install_process_hooks(process_hooks, sys_module, atexit_module, exit_note):
    """At each run open: the excepthook and atexit finalizer (once per
    process), the ``sys.exit`` note, and forget a ``sys.exit`` the
    application swallowed before this run opened."""
    process_hooks.install_once(
        sys_module, atexit_module,
        functools.partial(_finalize_open_runs, exit_note=exit_note),
        _note_uncaught_exception)
    exit_note.install(sys_module)
    exit_note.clear()


def _real_process_hooks():
    return functools.partial(
        _install_process_hooks, _PROCESS_HOOKS, sys, atexit, _EXIT_NOTE)


_PROCESS_HOOKS = ProcessHooks(os.getpid)
install_signal_handlers()
