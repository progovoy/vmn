#!/usr/bin/env python3
"""The in-process experiment SDK: ``start_run()`` and the ``Run`` it returns.

``vmn exp run`` supervises a child process and records what happened to it. That
is the wrong shape for a training script, which wants to record metrics from
*inside* the loop. ``start_run()`` is the same recorder, hosted by the workload
itself.

Records are deliberately identical to the CLI's: the verstr allocation, the
``metadata.yml``, the per-writer JSONL log and the ``run_state.yml`` schema all
come from the same helpers ``vmn exp run`` uses, so ``vmn exp list/show`` and the
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

from version_stamp.core import logging as vmn_logging
from version_stamp.core.background import Coalescing
from version_stamp.core.best_effort import BestEffort, quiet
from version_stamp.core.experiment_status import DEFAULT_HEARTBEAT_INTERVAL_SEC
from version_stamp.core.experiment_values import sanitize_entry
from version_stamp.core.experiment_writer import (
    append_entries_to_log,
    compute_artifact_info,
    create_log_entry,
    create_tags_entry,
    get_writer_id,
    save_artifact,
)
from version_stamp.core.utils import now_iso
from version_stamp.exp import (
    _resolve_app_name,  # noqa: F401  (one shared resolver)
    context,
    resume,
    signals,
    sysmetrics,
)
from version_stamp.exp.context import (  # noqa: F401  (re-exported API)
    _OPEN_RUNS,
    EXPERIMENT_ID_ENV,
    current_run,
)
from version_stamp.exp.create import SNAPSHOT_METADATA_ENV, create_record  # noqa: F401
from version_stamp.exp.heartbeat import Heartbeat
from version_stamp.exp.log_buffer import LogBuffer
from version_stamp.exp.ranks import NoOpRun, is_secondary_rank
from version_stamp.exp.run_artifacts import RunArtifacts
from version_stamp.exp.state_publisher import RunStatePublisher

# Stdlib logging, not VMN_LOGGER: an SDK user never calls init_stamp_logger, and
# a library emits records rather than configuring handlers.
_LOGGER = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL_SEC = 30
# How long finish() waits for the last remote writes before giving up on them.
FINAL_REMOTE_TIMEOUT_SEC = 60

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
    system_metrics=False,
    sync_interval_sec=DEFAULT_SYNC_INTERVAL_SEC,
    snapshot=True,
    run_id=None,
    all_ranks=False,
    name=None,
    tags=None,
):
    """Create an experiment (or reopen one), mark it running and return the ``Run``.

    ``app_name=None`` resolves the app from the current checkout. Use the result
    as a context manager, or call ``finish()`` yourself.

    With ``VMN_SNAPSHOT_METADATA`` set (a container built from ``vmn snapshot
    export``) no git checkout is needed: the run records against that snapshot
    into ``VMN_EXPERIMENT_DIR`` (or *storage*), exactly like the CLI.

    ``system_metrics=True`` records this process's CPU and memory (and GPU, with
    ``pynvml``) as ``sys_*`` metrics on every heartbeat.

    ``sync_interval_sec`` pushes the log to a remote store (when *storage* has
    one) at most that often, off the heartbeat thread. ``None``/``0`` syncs only
    on ``finish()``.

    ``snapshot=False`` records only the code identity (base commit and diff
    hash), with no patches or untracked tarball — for many lightweight runs.

    ``name`` is a human-readable run name, stored in ``metadata.yml`` and shown
    by ``vmn exp list``; ``tags`` (``{key: value}``) are set once the run opens.

    ``run_id`` (or ``VMN_RESUME_RUN_ID``) reopens an existing run of the app
    instead of creating one — a requeued job continuing where it was preempted.

    On a non-zero rank of a distributed job (``RANK``, ``LOCAL_RANK`` with
    ``WORLD_SIZE > 1``, or ``SLURM_PROCID``) this returns a :class:`NoOpRun`
    that records nothing, unless ``all_ranks=True``.
    """
    if not all_ranks and is_secondary_rank():
        return NoOpRun(app_name)
    # The reused CLI helpers log through VMN_LOGGER, which raises until something
    # initializes it — and a library must not call init_stamp_logger.
    vmn_logging.ensure_logger()

    prior_state = None
    ref = resume.requested_run_id(run_id)
    if ref:
        app_name, storage, verstr, prior_state = resume.locate(app_name, ref, storage)
    else:
        app_name, storage, verstr = create_record(
            app_name, note, params, parent, nested, storage, snapshot, name
        )

    run = Run(
        storage,
        app_name,
        verstr,
        heartbeat_interval_sec or DEFAULT_HEARTBEAT_INTERVAL_SEC,
        system_metrics=system_metrics,
        sync_interval_sec=sync_interval_sec,
        prior_state=prior_state,
        name=name,
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


class Run(RunArtifacts):
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
        signals.install(_finalize_signaled)
        self._heartbeat.start()

    def finish(self, exit_code=0):
        """Finalize the run. Idempotent: a second call changes nothing.

        Never raises for a storage failure (a flaky remote at the end of a long
        run is logged, not thrown at the workload), and always closes the run —
        it leaves the open-run registry and hands the env back either way.
        """
        self._finish(exit_code)

    def _finish(self, exit_code, **final_state):
        if self._finished:
            return
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
            self._close_remote_writers()
        finally:
            context.unregister(self)
            if not context.open_runs():
                signals.uninstall()

    def _close_remote_writers(self):
        # One deadline for both: they upload in parallel, so waiting for each
        # in turn would double the worst case.
        deadline = time.monotonic() + FINAL_REMOTE_TIMEOUT_SEC
        for what, writer in (("log", self._log_sync), ("state", self._state_publisher)):
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

    def log_artifact(self, path, name=None):
        """Store the file at *path* as artifact *name* (a relative ``a/b/c``
        path; default: its basename)."""
        info = compute_artifact_info(path)
        if name is not None:
            info["path"] = name
        save_artifact(self._storage, self.app_name, self.id, path, name=name)
        self._append(create_log_entry("artifact", **info))

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
    for run in list(reversed(context.open_runs())):
        try:
            run._finish(exit_code, **final_state)
        except Exception:
            _LOGGER.debug("Failed to finalize an abandoned run", exc_info=True)


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


atexit.register(_finalize_open_runs)
