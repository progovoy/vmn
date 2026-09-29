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

from vmn_exp._base import ensure_logger, now_iso
from vmn_exp.core.background import Coalescing
from vmn_exp.core.best_effort import BestEffort, quiet
from vmn_exp.core.inputs import create_input_entry
from vmn_exp.core.status import DEFAULT_HEARTBEAT_INTERVAL_SEC, positive_env_sec
from vmn_exp.core.values import sanitize_entry
from vmn_exp.core.writer import (
    append_entries_to_log,
    compute_artifact_info,
    create_log_entry,
    create_tags_entry,
    get_writer_id,
    save_artifact,
)
from vmn_exp.sdk import (
    _resolve_app_name,  # noqa: F401  (one shared resolver)
    context,
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
from vmn_exp.sdk.heartbeat import Heartbeat
from vmn_exp.sdk.log_buffer import LogBuffer
from vmn_exp.sdk.metric_defs import MetricDefinitions
from vmn_exp.sdk.output_capture import RunOutput
from vmn_exp.sdk.ranks import NoOpRun, is_secondary_rank
from vmn_exp.sdk.run_alerts import RunAlerts
from vmn_exp.sdk.run_artifacts import RunArtifacts
from vmn_exp.sdk.run_media import RunMedia
from vmn_exp.sdk.state_publisher import RunStatePublisher

# Stdlib logging, not VMN_LOGGER: an SDK user never calls init_stamp_logger, and
# a library emits records rather than configuring handlers.
_LOGGER = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL_SEC = 30
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

# Whether an uncaught exception has reached the top of this process. Only
# this flips the atexit-abandoned default from succeeded to failed:
# ``SystemExit`` never reaches ``sys.excepthook`` (CPython special-cases it
# before running atexit handlers), so a bare ``sys.exit(N)`` outside a
# context-managed run stays indistinguishable from a clean exit here — the
# same as it would be for any other process without our instrumentation.
_uncaught_exception_seen = False
_prev_excepthook = sys.excepthook


def _note_uncaught_exception(exc_type, exc_value, tb):
    global _uncaught_exception_seen
    _uncaught_exception_seen = True
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
    sync_interval_sec=DEFAULT_SYNC_INTERVAL_SEC,
    snapshot=True,
    run_id=None,
    all_ranks=False,
    name=None,
    tags=None,
    capture_env=None,
    capture_output=False,
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

    ``sync_interval_sec`` pushes the log to a remote store (when *storage* has
    one) at most that often, off the heartbeat thread. ``None``/``0`` syncs only
    on ``finish()``.

    ``snapshot=False`` records only the code identity (base commit and diff
    hash), with no patches or untracked tarball — for many lightweight runs.

    ``name`` is a human-readable run name, stored in ``metadata.yml`` and shown
    by ``vmn-exp list``; ``tags`` (``{key: value}``) are set once the run opens.

    ``run_id`` (or ``VMN_RESUME_RUN_ID``) reopens an existing run of the app
    instead of creating one — a requeued job continuing where it was preempted.

    On a non-zero rank of a distributed job (``RANK``, ``LOCAL_RANK`` with
    ``WORLD_SIZE > 1``, or ``SLURM_PROCID``) this returns a :class:`NoOpRun`
    that records nothing, unless ``all_ranks=True``.

    ``capture_output=True`` tees this process's stdout/stderr (fds 1 and 2, so
    subprocesses and C extensions too) into the run's ``output.log`` artifact,
    capped by ``VMN_EXP_OUTPUT_CAP_MB`` (default 10), uploaded every
    ``sync_interval_sec`` and at finish. Off by default: the process then
    writes to pipes, not its TTY.
    """
    if not all_ranks and is_secondary_rank():
        return NoOpRun(app_name)
    # The reused CLI helpers log through VMN_LOGGER, which raises until something
    # initializes it — and a library must not call init_stamp_logger.
    ensure_logger()

    prior_state = None
    ref = resume.requested_run_id(run_id)
    if ref:
        # Resume: locate the existing run; env stays as originally captured.
        app_name, storage, verstr, prior_state, exp_conf = resume.locate(
            app_name, ref, storage
        )
    else:
        app_name, storage, verstr, exp_conf = create_record(
            app_name, note, params, parent, nested, storage, snapshot, name,
            capture_env=capture_env,
        )

    run = Run(
        storage,
        app_name,
        verstr,
        heartbeat_interval_sec or DEFAULT_HEARTBEAT_INTERVAL_SEC,
        system_metrics=sysmetrics.enabled(system_metrics, exp_conf),
        sync_interval_sec=sync_interval_sec,
        prior_state=prior_state,
        name=name,
        capture_output=capture_output,
    )
    run._open()
    if prior_state is not None:
        _record_resume_inputs(run, note, params)
    if tags:
        run.set_tags(tags)
    return run


def _record_resume_inputs(run, note, params):
    """A resumed run's new note/params are appended, like any later entry."""
    if params:
        run.log_params(params)
    if note:
        run.log_note(note)


class Run(MetricDefinitions, RunArtifacts, RunMedia, RunAlerts):
    """One open experiment run: a metrics sink plus a liveness publisher."""

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
    ):
        self._storage = storage
        self.app_name = app_name
        self.id = verstr
        self.name = name
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
        self._state_publisher = RunStatePublisher(storage, app_name, verstr)
        self._log_buffer = LogBuffer(
            functools.partial(append_entries_to_log, storage, app_name, verstr)
        )
        self._chore_guard = quiet(_LOGGER)
        self._log_sync = Coalescing(
            functools.partial(
                self._chore_guard,
                "experiment log sync",
                storage.sync_log_to_remote,
                app_name,
                verstr,
            ),
            "vmn-exp-sync",
        )
        self._heartbeat = Heartbeat(self._beat, heartbeat_interval_sec)
        self._output = (
            RunOutput(storage, app_name, verstr) if capture_output else None
        )
        # No pid: this process *is* the workload.
        self._sampler = sysmetrics.Sampler(self.log_metrics, system_metrics)
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
            "pid": os.getpid(),
            "host": socket.gethostname(),
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

    def finish(self, exit_code=0):
        """Finalize the run. Idempotent: a second call changes nothing.

        Never raises for a storage failure (a flaky remote at the end of a long
        run is logged, not thrown at the workload), and always closes the run —
        it leaves the open-run registry and hands the env back either way.
        """
        self._finish(exit_code)

    def _finish(self, exit_code, **final_state):
        if self._record_final(exit_code, **final_state):
            self._close_remote_writers(_final_upload_deadline())

    def _record_final(self, exit_code, **final_state):
        """Write the run's last log entries and final state locally, queue their
        upload and close the run. False if it was finished already."""
        if self._finished:
            return False
        self._finished = True

        try:
            self._heartbeat.stop()
            duration = self._duration()
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
            if self._output is not None:
                self._record_guard("output log", self._record_output)
            # The log lands before the final state: a reader that sees the run
            # finished must also see everything it logged.
            self._record_guard("buffered log", self._log_buffer.close)
            self._record_guard(
                "final state",
                self._publish,
                state="finished",
                exit_code=exit_code,
                finished_at=now_iso(),
                duration_sec=duration,
                **final_state,
            )
            self._log_sync.submit(get_writer_id())
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
        self._record_guard(
            "error entry",
            self._append,
            create_log_entry("error", exception=type(exc).__name__, message=str(exc)),
        )
        self.finish(exit_code=1)
        return False  # never swallow — nor replace — the workload's exception

    # -- recording ---------------------------------------------------------

    def log_metric(self, key, value, step=None):
        self.log_metrics({key: value}, step=step)

    def log_metrics(self, mapping, step=None):
        entry = create_log_entry("metrics", values=dict(mapping))
        if step is not None:
            entry["step"] = step
        self._append(entry)

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
        path; default: its basename)."""
        info = compute_artifact_info(path)
        if name is not None:
            info["path"] = name
        self._save_artifact_file(path, name)
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
            Relative artifact path within this run.
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

    # Tags are mutable, and can be set on a finished run: each call appends a
    # `tags` entry, and readers fold them per key, last write wins.
    def set_tag(self, key, value):
        self.set_tags({key: value})

    def set_tags(self, tags):
        self._append(create_tags_entry(tags))

    def remove_tag(self, key):
        self._append(create_tags_entry(remove=[key]))

    # -- internals ---------------------------------------------------------

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
        self._publish(heartbeat=now_iso(), heartbeat_seq=self._state["heartbeat_seq"] + 1)

    def _maybe_sync(self):
        if not self._sync_interval_sec:
            return
        if time.monotonic() - self._last_sync < self._sync_interval_sec:
            return
        self._last_sync = time.monotonic()
        self._log_sync.submit(get_writer_id())
        if self._output is not None:
            self._output.request_upload()


def _finalize_open_runs(exit_code=None, **final_state):
    """Never leave a run claiming ``running`` just because nobody finished it.

    With no explicit *exit_code* (the atexit case) a clean process exit reads
    as succeeded, and only a genuinely uncaught exception reads as failed —
    see ``_uncaught_exception_seen``. ``_finalize_signaled`` always passes an
    explicit code, so a killed process is unaffected.

    Only this process's runs: a forked child exiting normally must not finalize
    — and so mark failed — the parent's still-running run.
    """
    if exit_code is None:
        exit_code = ABANDONED_EXIT_CODE if _uncaught_exception_seen else 0
    # Every run's final state first, then one shared wait for all the uploads:
    # a hung remote must not spend the whole budget on the first run.
    recorded = [
        run
        for run in reversed(context.open_runs())
        if _quietly(run._record_final, exit_code, **final_state)
    ]
    deadline = _final_upload_deadline()
    for run in recorded:
        _quietly(run._close_remote_writers, deadline)


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
    """A run a signal ended exits ``128 + N``, as a shell reports it."""
    _finalize_open_runs(128 + signum, received_signal=signal.Signals(signum).name)


def install_signal_handlers():
    """Finalize open runs on SIGTERM. Call from the main thread.

    Done already when ``vmn_exp.sdk`` is imported on the main thread; call it
    again after installing a SIGTERM handler of your own (it is chained), or
    when the SDK is first imported from a worker thread.
    """
    signals.install(_finalize_signaled, timeout=final_upload_timeout_sec)


atexit.register(_finalize_open_runs)
install_signal_handlers()
