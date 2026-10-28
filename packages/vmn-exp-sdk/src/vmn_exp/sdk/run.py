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
import time
import uuid

from vmn_exp._base import ensure_logger, now_iso
from vmn_exp.core.background import Coalescing
from vmn_exp.core.best_effort import BestEffort, quiet
from vmn_exp.core.inputs import create_input_entry
from vmn_exp.core.intent import build_intent_entry
from vmn_exp.core.metric_compact import compact_by
from vmn_exp.core.rerun import RUNNER_SDK, repo_relative_cwd
from vmn_exp.core.run_error import error_from_exception, error_from_message
from vmn_exp.core.run_intervals import (
    DEFAULT_SYNC_INTERVAL_SEC,
    resolve_heartbeat_sec,
    resolve_sync_sec,
)
from vmn_exp.core.status import positive_env_sec
from vmn_exp.core.storage_resolve import _try_repo_root
from vmn_exp.core.values import sanitize_entry
from vmn_exp.core.writer import (
    append_entries_to_log,
    compute_artifact_info,
    create_log_entry,
    create_tags_entry,
    own_stream,
    save_artifact,
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
)
from vmn_exp.sdk.create import SNAPSHOT_METADATA_ENV, create_record  # noqa: F401
from vmn_exp.sdk import fork_safety  # noqa: F401  (registers the fork handlers)
from vmn_exp.sdk.background_gate import BackgroundGate, RunBackground
from vmn_exp.sdk.heartbeat import Heartbeat
from vmn_exp.sdk.log_buffer import LogBuffer
from vmn_exp.sdk.metric_defs import MetricDefinitions
from vmn_exp.sdk.mode import is_disabled
from vmn_exp.sdk.output_capture import RunOutput
from vmn_exp.sdk.ranks import NoOpRun, is_secondary_rank
from vmn_exp.sdk.run_alerts import RunAlerts
from vmn_exp.sdk.run_artifacts import RunArtifacts, checked_artifact_name
from vmn_exp.storage.ship_state import finalizing
from vmn_exp.storage.files import user_artifact_path
from vmn_exp.sdk.media_uploads import MediaUploads
from vmn_exp.sdk.run_media import RunMedia
from vmn_exp.sdk.run_metrics import RunMetrics
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
# How long finish() waits for run.alert() deliveries still in flight.
ALERT_DRAIN_SEC = 5

# A run that reached interpreter exit still open was abandoned. Most of the
# time that is just an mlflow-style "forgot to call finish()" — the process
# fell off the end cleanly — and must read as succeeded, like the workload's
# own exit code says. Only a genuinely uncaught exception (see
# ``_note_uncaught_exception`` below) makes it read as failed instead.
ABANDONED_EXIT_CODE = 1

# The uncaught exception that reached the top of this process, if any,
# recorded as the abandoned runs' ``error``. Only it flips the atexit-abandoned
# default from succeeded to failed: ``SystemExit`` never reaches
# ``sys.excepthook`` (CPython special-cases it before running atexit
# handlers), so a bare ``sys.exit(N)`` outside a context-managed run stays
# indistinguishable from a clean exit here — the same as it would be for any
# other process without our instrumentation.
_uncaught_exception = None
_prev_excepthook = sys.excepthook


def _note_uncaught_exception(exc_type, exc_value, tb):
    global _uncaught_exception
    _uncaught_exception = exc_value
    _prev_excepthook(exc_type, exc_value, tb)


sys.excepthook = _note_uncaught_exception


def start_run(
    app_name=None,
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
    on_sigterm=release.FAIL,
):
    """Create an experiment (or reopen one), mark it running and return the ``Run``.

    ``app_name=None`` resolves the app from the current checkout. Use the result
    as a context manager, or call ``finish()`` yourself.

    With ``VMN_SNAPSHOT_METADATA`` set (a container built from ``vmn-exp
    export``) no git checkout is needed: the run records against that snapshot
    into ``VMN_EXPERIMENT_DIR`` (or *storage*), exactly like the CLI.

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
    With ``rewind_to_step=N`` too, the reopened run's history past step N is
    hidden (refused while the run is live elsewhere).

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

    ``mode="disabled"`` (or ``VMN_MODE=disabled``; an explicit *mode* wins)
    returns a :class:`NoOpRun` without touching git or the store.

    ``intent`` (with ``intent_keywords``) says what the run is for, as with
    :meth:`Run.set_intent` once the run opens — a resumed run gets one only
    when given. A bad one raises ValueError before anything is created.

    ``on_sigterm`` is what the SDK's SIGTERM handler does with the run:
    ``"fail"`` finishes it with exit code 143; ``"release"`` hands it back
    unfinished (:meth:`Run.release`) for a retry to reopen with ``run_id=``.
    """
    release.check_on_sigterm(on_sigterm)
    if is_disabled(mode):
        return NoOpRun(app_name, disabled=True)
    if not all_ranks and is_secondary_rank():
        return NoOpRun(app_name)
    # The reused CLI helpers log through VMN_LOGGER, which raises until something
    # initializes it — and a library must not call init_stamp_logger.
    ensure_logger()
    _check_intent(intent, intent_keywords)

    prior_state, start_step = None, None
    ref = resume.requested_run_id(run_id)
    fork.check_modes(ref, fork_from, rewind_to_step)
    if ref:
        # Resume: locate the existing run; env stays as originally captured.
        app_name, storage, verstr, prior_state, exp_conf = resume.locate(
            app_name, ref, storage
        )
        if rewind_to_step is not None:
            start_step = fork.rewind(storage, app_name, verstr, prior_state, rewind_to_step)
    else:
        if fork_from:
            app_name, storage, source, fork_step = fork.locate_source(
                app_name, fork_from, fork_step, storage
            )
        app_name, storage, verstr, exp_conf = create_record(
            app_name, note, params, parent, nested, storage, name,
            capture_env=capture_env,
        )
        if fork_from:
            start_step = fork.seed(storage, app_name, verstr, source, fork_step)

    run = Run(
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
    )
    run.start_step = start_step
    run._steps = StepCounter(
        first_step(storage, app_name, verstr, start_step, prior_state is not None)
    )
    run._open()
    if prior_state is not None:
        _record_resume_inputs(run, note, params)
    if tags:
        run.set_tags(tags)
    if intent is not None:
        run.set_intent(intent, keywords=intent_keywords)
    return run


def _check_intent(intent, keywords):
    if intent is not None:
        build_intent_entry(intent, keywords)
    elif keywords is not None:
        raise ValueError("intent_keywords needs an intent")


def _record_resume_inputs(run, note, params):
    """A resumed run's new note/params are appended, like any later entry."""
    if params:
        run.log_params(params)
    if note:
        run.log_note(note)


def _checkout_relative_cwd():
    """This process's cwd relative to its checkout; None when git-free."""
    if os.environ.get(SNAPSHOT_METADATA_ENV):
        return None
    return repo_relative_cwd(os.getcwd(), _try_repo_root())


class Run(RunMetrics, MetricDefinitions, RunArtifacts, RunMedia, RunAlerts, RunBackground):
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
    ):
        self._storage = storage
        self._on_sigterm = on_sigterm
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
        # not the run: `current_run()` there is None and atexit leaves it alone.
        self.pid = os.getpid()

        self._finished = False
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
        self._state_publisher = RunStatePublisher(storage, app_name, verstr, self._gate)
        self._log_buffer = LogBuffer(
            functools.partial(append_entries_to_log, storage, app_name, verstr),
            self._gate,
        )
        self._chore_guard = quiet(_LOGGER)
        self._log_sync = Coalescing(
            self._gate.wrap(functools.partial(
                self._chore_guard,
                "experiment log sync",
                sync_to_remote,
                storage,
                app_name,
                verstr,
            )),
            "vmn-exp-sync",
        )
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
            "attempt": uuid.uuid4().hex[:12],
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
        self._publish()
        context.register(self)
        install_signal_handlers()
        if self._output is not None:
            self._chore_guard("output capture", self._output.start)
        self._heartbeat.start()

    def finish(self, exit_code=0, error=None):
        """Finalize the run. Idempotent: a second call changes nothing.

        *error* — an exception or a message — is recorded as the final run
        state's ``error`` (and an ``error`` log entry), whatever *exit_code* is.

        Never raises for a storage failure (a flaky remote at the end of a long
        run is logged, not thrown at the workload), and always closes the run —
        it leaves the open-run registry and hands the env back either way.
        """
        self._finish(exit_code, error=error)

    def release(self, reason=None):
        """Hand the run back unfinished, for another attempt to reopen with
        ``start_run(run_id=...)``: everything logged so far is flushed and
        synced, recording stops, and the run reads as waiting (``created``)
        with ``end_reason: released`` (*reason* as ``release_reason``).
        Idempotent; a no-op on a finished run. Never raises for a storage
        failure, like :meth:`finish`."""
        deadline = _final_upload_deadline()
        if self._record_release(deadline, reason=reason):
            self._close_remote_writers(deadline)

    def _finish(self, exit_code, error=None, **final_state):
        deadline = _final_upload_deadline()
        if self._record_final(exit_code, deadline, error=error, **final_state):
            self._close_remote_writers(deadline)

    def _record_error(self, error):
        """Append the ``error`` log entry of *error*; return its run-state mapping."""
        if isinstance(error, BaseException):
            recorded = error_from_exception(error)
            entry = create_log_entry(
                "error",
                exception=type(error).__name__,
                message=recorded["message"],
                traceback=recorded["traceback"],
            )
        else:
            recorded = error_from_message(error)
            entry = create_log_entry("error", message=recorded["message"])
        self._record_guard("error entry", self._append, entry)
        return recorded

    def _record_final(self, exit_code, deadline, error=None, **final_state):
        """Write the run's last log entries and final state locally, queue their
        upload and close the run. False if it was finished already."""

        def outcome():
            duration = self._duration()
            if error is not None:
                recorded = self._record_guard("error", self._record_error, error)
                if recorded is not None:
                    final_state["error"] = recorded
            self._record_guard(
                "run entry",
                self._append,
                create_log_entry(
                    "run",
                    command=self._state["command"],
                    exit_code=exit_code,
                    duration_sec=duration,
                ),
            )
            return dict(state="finished", exit_code=exit_code, finished_at=now_iso(),
                        duration_sec=duration, **final_state)

        return self._close_attempt(deadline, outcome, alerts=True)

    def _record_release(self, deadline, reason=None, signal=None):
        """:meth:`_record_final` of a released attempt (no exit code, no alerts)."""
        return self._close_attempt(
            deadline, lambda: release.released_state(self._duration(), reason, signal))

    def _close_attempt(self, deadline, outcome, alerts=False):
        """Stop recording, write *outcome()*'s state last, queue the uploads
        and close the run. False if it was closed already.

        Media files are waited for (until *deadline*) first: their entries are
        appended as they are stored, so they must land before the final flush.
        """
        if self._finished:
            return False
        self._finished = True
        # A paused run still drains: its last uploads must not wait for a resume.
        self._gate.release()

        try:
            # Before the heartbeat stops: a long final upload is not a stuck run.
            self._record_guard(
                "media files",
                self._close_media_uploads,
                max(0.0, deadline - time.monotonic()),
            )
            self._heartbeat.stop()
            final_state = outcome()
            if self._output is not None:
                self._record_guard("output log", self._record_output)
            # The log lands before the final state: a reader that sees the run
            # finished must also see everything it logged.
            self._record_guard("buffered log", self._log_buffer.close)
            self._record_guard("final state", self._publish, **final_state)
            self._log_sync.submit(None)
            if alerts:
                self._record_guard("alerts", self._finish_alerts, ALERT_DRAIN_SEC)
        finally:
            context.unregister(self)
        return True

    def _record_output(self):
        self._append(self._output.stop())

    def _close_remote_writers(self, deadline):
        # One deadline for all: they upload in parallel, so waiting for each
        # in turn would double the worst case.
        writers = [("log", self._log_sync), ("state", self._state_publisher)]
        if self._output is not None:
            writers.append(("output log", self._output))
        for what, writer in writers:
            if not writer.close(max(0.0, deadline - time.monotonic())):
                _LOGGER.warning(f"vmn: the final {what} of run {self.id} is still uploading")
        compact_by(self._storage, self.app_name, self.id,
                   own_stream(self._storage, self.app_name, self.id), deadline)

    def _duration(self):
        return round(self._elapsed_before + time.monotonic() - self._monotonic_start, 3)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._finished:
            return False
        if exc is None:
            self.finish()
            return False
        if isinstance(exc, SystemExit):
            # sys.exit(0) inside the block is a clean, intentional exit — not
            # an error — and the real code (when non-zero) beats a generic 1.
            self.finish(exit_code=_system_exit_code(exc))
            return False
        self.finish(exit_code=1, error=exc)
        return False  # never swallow — nor replace — the workload's exception

    # -- recording ---------------------------------------------------------

    def log_params(self, mapping):
        # A `params` entry, not a rewrite of the `create` entry: the log is
        # append-only, so readers fold later params in rather than see them move.
        self._append(create_log_entry("params", params=dict(mapping)))

    def log_note(self, text):
        self._append(create_log_entry("note", text=text))

    def log_input(self, uri, name=None, digest=None, kind=None):
        """Record that this run consumed the artifact at *uri*.

        *name* defaults to the URI basename (without extension). *digest* and
        *kind* are optional provenance hints (e.g. ``"sha256:..."`` and
        ``"dataset"``). Multiple calls are independent log entries; fold logic
        merges them latest-write-wins by name.
        """
        self._append(create_input_entry(uri, name=name, digest=digest, kind=kind, ts=now_iso()))

    def log_artifact(self, path, name=None):
        """Store the file at *path* as artifact *name* (a relative ``a/b/c``
        path; default: its basename), at ``artifacts/<name>`` in the run."""
        info = compute_artifact_info(path)
        if name is not None:
            info["path"] = user_artifact_path(checked_artifact_name(name))
        self._save_artifact_file(path, info["path"])
        self._append(create_log_entry("artifact", **info))

    def _save_artifact_file(self, path, name):
        save_artifact(self._storage, self.app_name, self.id, path, name=name)

    def register_model(self, name, artifact_path=None, alias=None, description=None, *, storage=None):
        """Register this run as a model version in the registry.

        Convenience wrapper around :func:`~vmn_exp.sdk.models.register_model`
        that pre-fills *run*, *app_name* and *storage* from this run.

        Parameters
        ----------
        name:
            Model name.
        artifact_path:
            Record-relative path of the stored file (``artifacts/<name>``).
        alias:
            If given, immediately point this alias at the new version.
        description:
            Human-readable description of this version.
        storage:
            Override the storage; defaults to this run's storage.
        """
        from vmn_exp.sdk.models import register_model as _register_model

        return _register_model(
            name,
            run=self,
            artifact_path=artifact_path,
            alias=alias,
            description=description,
            storage=storage,
        )

    def use_model(self, ref, *, storage=None):
        """Record that this run used model *ref*; see :mod:`vmn_exp.sdk.usage`."""
        from vmn_exp.sdk.usage import use_model

        return use_model(ref, run=self, storage=storage)

    def use_dataset(self, ref, *, storage=None):
        """Record that this run used dataset *ref*; see :mod:`vmn_exp.sdk.usage`."""
        from vmn_exp.sdk.usage import use_dataset

        return use_dataset(ref, run=self, storage=storage)

    # Tags are mutable, and can be set on a finished run: each call appends a
    # `tags` entry, and readers fold them per key, last write wins.
    def set_tag(self, key, value):
        self.set_tags({key: value})

    def set_tags(self, tags):
        self._append(create_tags_entry(tags))

    def remove_tag(self, key):
        self._append(create_tags_entry(remove=[key]))

    def set_intent(self, text, keywords=None, generator=None):
        """Say what this run is for: markdown *text* (cut at 16 KiB),
        *keywords* (synonyms, the problem's usual names) and the *generator*
        (model id) that wrote it, if any. Matched by similar-run search; the
        latest intent wins, also on a finished run — nothing ships its log
        any more, so the entry is synced to the remote at once."""
        self._append(stamped_entry(build_intent_entry(text, keywords, generator)))
        if self._finished:
            self._record_guard("intent", sync_to_remote, self._storage, self.app_name,
                               self.id)

    def similar(self, top=10):
        """The past runs most like this one — its code, changes, params,
        inputs and intent so far: :func:`vmn_exp.sdk.reader.similar_runs`
        items, under the checkout's conf."""
        from vmn_exp.core.similar_search import find

        self._log_buffer.flush()
        return find(self._storage, self.app_name, self.id, self._exp_conf, top=top)

    # -- internals ---------------------------------------------------------

    def _after_fork_in_child(self):
        # The child has none of this run's threads (and is not its writer).
        self._gate.after_fork_in_child()
        self._log_buffer.after_fork_in_child()

    def _append(self, entry):
        entry = sanitize_entry(entry)
        if entry is not None:
            self._log_buffer.append(entry)

    def _publish(self, **updates):
        self._state.update(updates)
        self._state_publisher.publish(self._state)

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
        self._log_sync.submit(None)
        if self._output is not None:
            self._output.request_upload()


def _finalize_open_runs(exit_code=None, **final_state):
    """Never leave a run claiming ``running`` just because nobody finished it.

    With no explicit *exit_code* (the atexit case) a clean process exit reads
    as succeeded, and only a genuinely uncaught exception reads as failed —
    see ``_uncaught_exception``. ``_finalize_signaled`` always passes an
    explicit code, so a killed process is unaffected.

    Only this process's runs: a forked child exiting normally must not finalize
    — and so mark failed — the parent's still-running run. A run opened with
    ``on_sigterm="release"`` is released instead when a signal ended it
    (``final_state["signal"]``).
    """
    error = None
    if exit_code is None:
        exit_code = ABANDONED_EXIT_CODE if _uncaught_exception is not None else 0
        error = _uncaught_exception
    # One shared deadline for every run's uploads: a hung remote must not
    # spend the whole budget on each run in turn. Media files are waited for
    # while recording (their entries must precede the final flush); the rest
    # of the uploads after every run's final state is written.
    deadline = _final_upload_deadline()
    recorded = [
        run
        for run in reversed(context.open_runs())
        if _quietly(_end_attempt, run, deadline, exit_code, error, final_state)
    ]
    for run in recorded:
        _quietly(run._close_remote_writers, deadline)


def _end_attempt(run, deadline, exit_code, error, final_state):
    if final_state.get("signal") and run._on_sigterm == release.RELEASE:
        return run._record_release(deadline, signal=final_state["signal"])
    return run._record_final(exit_code, deadline, error=error, **final_state)


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


def _final_upload_deadline():
    return time.monotonic() + final_upload_timeout_sec()


def _system_exit_code(exc):
    """``sys.exit()``'s effective process exit code, as the interpreter itself
    computes it: no argument (or ``None``) is 0, a non-int argument (a message)
    is printed and counts as 1, anything else is used as-is."""
    code = exc.code
    if code is None:
        return 0
    return code if isinstance(code, int) else 1


def _finalize_signaled(signum):
    """A run a signal ended exits ``128 + N``, as a shell reports it — or is
    released, when it was opened with ``on_sigterm="release"``."""
    name = signal.Signals(signum).name
    with finalizing():
        _finalize_open_runs(128 + signum, received_signal=name, signal=name)


def install_signal_handlers():
    """Finalize open runs on SIGTERM. Call from the main thread.

    Done already when ``vmn_exp.sdk`` is imported on the main thread; call it
    again after installing a SIGTERM handler of your own (it is chained), or
    when the SDK is first imported from a worker thread.
    """
    signals.install(_finalize_signaled, timeout=final_upload_timeout_sec)


atexit.register(_finalize_open_runs)
install_signal_handlers()
