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
import contextlib
import logging
import os
import socket
import sys
import time
from types import SimpleNamespace

import yaml

from version_stamp.cli.constants import INIT_FILENAME

# Still upward, and deliberately so: creating an experiment record needs the git
# snapshot capture and the storage factory, both of which live in
# version_stamp/cli/snapshot.py. Everything that merely *shapes* a record comes
# from version_stamp.core.experiment_writer below. Lifting exp/ into its own
# distribution needs these to move into core next.
from version_stamp.cli.experiment import (
    _experiment_create_core,
    _get_experiment_storage,
    _resolve_parent,
)
from version_stamp.cli.snapshot import _resolve_verstr
from version_stamp.core import logging as vmn_logging
from version_stamp.core.best_effort import BestEffort, quiet
from version_stamp.core.constants import VMN_BE_TYPE_GIT
from version_stamp.core.experiment_from_snapshot import create_from_snapshot
from version_stamp.core.experiment_status import DEFAULT_HEARTBEAT_INTERVAL_SEC
from version_stamp.core.experiment_writer import (
    append_to_log,
    compute_artifact_info,
    create_log_entry,
    get_repo_lock,
    get_writer_id,
    merge_conf_into_params,
    merge_env_into_params,
    save_artifact,
    save_run_state,
)
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import now_iso, resolve_root_path
from version_stamp.exp import _resolve_app_name, context, sysmetrics
from version_stamp.exp.context import (  # noqa: F401  (re-exported API)
    _OPEN_RUNS,
    EXPERIMENT_ID_ENV,
    current_run,
)
from version_stamp.exp.heartbeat import Heartbeat

# Stdlib logging, not VMN_LOGGER: an SDK user never calls init_stamp_logger, and
# a library emits records rather than configuring handlers.
_LOGGER = logging.getLogger(__name__)

SNAPSHOT_METADATA_ENV = "VMN_SNAPSHOT_METADATA"
DEFAULT_SYNC_INTERVAL_SEC = 30

# The repo state `vmn exp create` demands, and what it tolerates — the SDK
# cold-starts on exactly the same terms.
_EXPECTED_STATUS = {"repo_tracked", "app_tracked"}
_OPTIONAL_STATUS = {
    "repos_exist_locally",
    "detached",
    "pending",
    "outgoing",
    "version_not_matched",
    "dirty_deps",
    "deps_synced_with_conf",
}
_DIRTY_OK = {"pending", "outgoing"}

# A run that reached interpreter exit still open was abandoned — the workload
# raised past us, called sys.exit(), or simply forgot to finish. It did not
# succeed, so it must not read as succeeded.
ABANDONED_EXIT_CODE = 1


def _stamped_apps():
    from version_stamp.cli.completion import _complete_apps

    return _complete_apps("")


def _build_vcs(app_name):
    from version_stamp.stamping.publisher import VersionControlStamper

    return VersionControlStamper(
        {
            "root": False,
            "name": app_name,
            "root_path": resolve_root_path(),
            "be_type": VMN_BE_TYPE_GIT,
        }
    )


def _cold_start(vcs):
    """Auto-initialize vmn tracking and a 0.0.0 baseline, as ``vmn exp`` does.

    ``vmn exp create``/``run`` work in a fresh repo — they init the repo and the
    app on first use. ``start_run`` is the in-process equivalent, so it must too,
    and it calls the very same CLI helpers rather than growing its own init.
    """
    from version_stamp.cli.commands import _get_repo_status, _init_app, handle_init

    # An untracked repo or app is the cold-start case this function exists to
    # handle, so it must not be announced as an error first — that made a
    # successful first run look like a crash.
    status = _get_repo_status(
        vcs,
        _EXPECTED_STATUS,
        _OPTIONAL_STATUS,
        suppress_errors={"repo_tracked", "app_tracked"},
    )
    if not status.error:
        return

    be = vcs.backend
    initialized = False
    vmn_init_file = os.path.join(vcs.vmn_root_path, ".vmn", INIT_FILENAME)

    if "repo_tracked" not in status.state and not be.is_path_tracked(vmn_init_file):
        # handle_init only ever reads vmn_ctx.vcs, so there is no argparse
        # namespace to fabricate.
        if handle_init(SimpleNamespace(vcs=vcs), extra_optional=_DIRTY_OK) != 0:
            raise RuntimeError(_cold_start_failure(vcs.name, "initialize the repo"))
        initialized = True

    if "app_tracked" not in status.state and not be.is_path_tracked(vcs.app_dir_path):
        if _init_app(vcs, "0.0.0", extra_optional=_DIRTY_OK):
            raise RuntimeError(_cold_start_failure(vcs.name, "stamp a baseline"))
        initialized = True

    if initialized:
        vcs.update_attrs_from_app_conf_file()
        vcs.initialize_backend_attrs()


def _cold_start_failure(app_name, what):
    return (
        f"Could not {what} for '{app_name}' automatically. "
        f"Run 'vmn stamp -r patch {app_name}' once, then start the run again."
    )


def _build_storage(vcs):
    params = {"backend": "local", "prefix": "vmn-experiments"}
    merge_conf_into_params(vcs, params)
    return _get_experiment_storage(vcs, params)


def _pick_parent(storage, app_name, parent, nested):
    """Resolve the parent experiment, following the CLI's validation policy.

    Precedence: an explicit ``parent`` (a bad one is a hard error), then the
    calling context's open run when ``nested``, then ``VMN_EXPERIMENT_ID`` (a
    stale one is warned about and dropped — the outer run may have been pruned,
    which is no reason to fail this one).

    ``VMN_EXPERIMENT_ID`` naming a run another thread of this process has open is
    a sibling's export, not a launcher: it is skipped in favour of the value the
    process was started with.
    """
    if parent:
        resolved, err = _resolve_parent(
            storage, app_name, SimpleNamespace(parent=parent)
        )
        if err:
            raise ValueError(f"Unknown parent experiment: {parent}")
        return resolved

    enclosing = current_run() if nested else None
    if enclosing is not None:
        return enclosing.id

    ref = os.environ.get(EXPERIMENT_ID_ENV)
    if ref and context.is_foreign_sibling(ref):
        ref = context.launcher_experiment_id()
    return _resolve_env_parent(storage, app_name, ref)


def _resolve_env_parent(storage, app_name, ref):
    """An env-provided parent: resolved against storage, dropped when stale."""
    if not ref:
        return None
    verstr, err = _resolve_verstr(storage, app_name, ref, kind="experiment")
    if err:
        VMN_LOGGER.warning(f"Ignoring stale VMN_EXPERIMENT_ID '{ref}': {err}")
        return None
    return verstr


def _snapshot_app_names(meta_path):
    """The app an exported snapshot's metadata names, as resolver candidates."""
    if os.path.isdir(meta_path):
        meta_path = os.path.join(meta_path, "vmn_metadata.yml")
    try:
        with open(meta_path) as f:
            meta = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return []
    app = meta.get("app_name") if isinstance(meta, dict) else None
    return [app] if app else []


def _snapshot_mode_storage():
    """Where a git-less run records, as the CLI does: ``VMN_EXPERIMENT_DIR``
    and/or the ``VMN_EXPERIMENT_BUCKET`` it syncs to."""
    params = {"backend": "local", "prefix": "vmn-experiments"}
    merge_env_into_params(params)
    try:
        return _get_experiment_storage(None, params)
    except ValueError:
        raise ValueError(
            "No experiment store for a run without a git checkout: "
            "set VMN_EXPERIMENT_DIR and/or VMN_EXPERIMENT_BUCKET (or pass storage=)."
        )


def _create_from_snapshot(
    app_name, meta_path, note, create_data, parent, nested, storage
):
    """Container mode: record against an exported snapshot, no git needed."""
    app_name = _resolve_app_name(app_name, lambda: _snapshot_app_names(meta_path))
    if storage is None:
        storage = _snapshot_mode_storage()
    # A shared VMN_EXPERIMENT_DIR is the only thing concurrent git-less workers
    # have in common: serialize verstr allocation on it, like a checkout's lock.
    lock_root = os.environ.get("VMN_EXPERIMENT_DIR")
    if lock_root:
        os.makedirs(os.path.join(lock_root, ".vmn"), exist_ok=True)
    with get_repo_lock(lock_root) if lock_root else contextlib.nullcontext():
        verstr, err = create_from_snapshot(
            storage,
            app_name,
            meta_path,
            note=note,
            extra_create_data=create_data,
            parent=_pick_parent(storage, app_name, parent, nested),
        )
    return app_name, storage, verstr, err


def _create_in_checkout(app_name, note, create_data, parent, nested, storage):
    """The normal mode: cold-start if needed, then snapshot the git checkout."""
    app_name = _resolve_app_name(app_name, _stamped_apps)
    root_path = resolve_root_path()
    os.makedirs(os.path.join(root_path, ".vmn"), exist_ok=True)

    # Cold start inits the repo and stamps a baseline, and verstr allocation
    # scans for a free `.rN` - both must not race a concurrent vmn. The vcs is
    # built under the lock too: one built before it would miss an init another
    # worker finished while this one waited. The rest of the run writes only
    # inside its own experiment directory, so the lock is scoped to creation and
    # never held for the life of the run.
    with get_repo_lock(root_path):
        vcs = _build_vcs(app_name)
        _cold_start(vcs)
        if storage is None:
            storage = _build_storage(vcs)

        verstr, err = _experiment_create_core(
            vcs,
            storage,
            note=note,
            extra_create_data=create_data,
            parent=_pick_parent(storage, app_name, parent, nested),
        )
    return app_name, storage, verstr, err


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
):
    """Create an experiment, mark it running and return the open ``Run``.

    ``app_name=None`` resolves the app from the current checkout. Use the result
    as a context manager, or call ``finish()`` yourself.

    With ``VMN_SNAPSHOT_METADATA`` set (a container built from ``vmn snapshot
    export``) no git checkout is needed: the run records against that snapshot
    into ``VMN_EXPERIMENT_DIR`` (or *storage*), exactly like the CLI.

    ``system_metrics=True`` records this process's CPU and memory (and GPU, with
    ``pynvml``) as ``sys_*`` metrics on every heartbeat. Off by default: it adds
    a log entry per beat, which a run that only wants its own metrics should not
    pay for.

    ``sync_interval_sec`` pushes the log to a remote store (when *storage* has
    one) at most that often, from the heartbeat thread, so a run killed mid-way
    still leaves its metrics behind. ``None``/``0`` syncs only on ``finish()``.
    """
    # The reused CLI helpers log through VMN_LOGGER, which raises until something
    # initializes it — and a library must not call init_stamp_logger.
    vmn_logging.ensure_logger()
    # Same shape as the CLI's `-f file` params, so _get_latest_metrics and
    # `exp diff` pick them up unchanged.
    create_data = {"params": dict(params)} if params else None
    meta_path = os.environ.get(SNAPSHOT_METADATA_ENV)
    if meta_path:
        app_name, storage, verstr, err = _create_from_snapshot(
            app_name, meta_path, note, create_data, parent, nested, storage
        )
    else:
        app_name, storage, verstr, err = _create_in_checkout(
            app_name, note, create_data, parent, nested, storage
        )
    if err:
        raise RuntimeError(
            f"Failed to create an experiment for '{app_name}' (error {err}). "
            f"Run 'vmn exp create {app_name}' to see what the CLI reports."
        )

    run = Run(
        storage,
        app_name,
        verstr,
        heartbeat_interval_sec or DEFAULT_HEARTBEAT_INTERVAL_SEC,
        system_metrics=system_metrics,
        sync_interval_sec=sync_interval_sec,
    )
    run._open()
    return run


class Run:
    """One open experiment run: a metrics sink plus a liveness publisher."""

    def __init__(
        self,
        storage,
        app_name,
        verstr,
        heartbeat_interval_sec,
        system_metrics=False,
        sync_interval_sec=DEFAULT_SYNC_INTERVAL_SEC,
    ):
        self._storage = storage
        self.app_name = app_name
        self.id = verstr
        # The process that owns the run. A forked child inherits this object but
        # not the run: `current_run()` there is None and atexit leaves it alone.
        self.pid = os.getpid()

        self._finished = False
        self._monotonic_start = time.monotonic()
        self._sync_interval_sec = sync_interval_sec
        self._last_sync = self._monotonic_start
        self._ctx_prev = None

        started_at = now_iso()
        self._state = {
            "state": "running",
            # There is no child command here — the run *is* this process. Its
            # argv is the honest answer, and consumers read the key.
            "command": list(sys.argv),
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": started_at,
            "heartbeat": started_at,
            "heartbeat_interval_sec": heartbeat_interval_sec,
            "exit_code": None,
            "finished_at": None,
            "duration_sec": None,
        }
        self._heartbeat = Heartbeat(self._beat, heartbeat_interval_sec)
        # No pid: this process *is* the workload.
        self._sampler = sysmetrics.Sampler(self.log_metrics, system_metrics)
        # Recording the run's outcome warns once per step; heartbeat chores and
        # syncs are routine enough to stay at debug.
        self._record_guard = BestEffort(
            _LOGGER,
            lambda what, exc: f"vmn: could not record the {what} of run {self.id}: {exc}",
        )
        self._chore_guard = quiet(_LOGGER)

    # -- lifecycle ---------------------------------------------------------

    def _open(self):
        self._publish()
        context.register(self)
        self._heartbeat.start()

    def finish(self, exit_code=0):
        """Finalize the run. Idempotent: a second call changes nothing.

        Never raises for a storage failure (a flaky remote at the end of a long
        run is logged, not thrown at the workload), and always closes the run —
        it leaves the open-run registry and hands the env back either way.
        """
        if self._finished:
            return
        self._finished = True

        try:
            self._heartbeat.stop()
            duration = round(time.monotonic() - self._monotonic_start, 3)
            self._record_guard(
                "final state",
                self._publish,
                state="finished",
                exit_code=exit_code,
                finished_at=now_iso(),
                duration_sec=duration,
            )
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
            self._sync()
        finally:
            context.unregister(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._finished:
            return False
        if exc is None:
            self.finish()
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

    def log_artifact(self, path):
        info = compute_artifact_info(path)
        save_artifact(self._storage, self.app_name, self.id, path)
        self._append(create_log_entry("artifact", **info))

    # -- internals ---------------------------------------------------------

    def _append(self, entry):
        append_to_log(self._storage, self.app_name, self.id, entry)

    def _publish(self, **updates):
        save_run_state(self._storage, self.app_name, self.id, self._state, **updates)

    def _beat(self):
        # Independent chores: a failed heartbeat write must not skip the sync
        # that would get the log off this box, nor the other way round.
        for chore in (self._publish_heartbeat, self._sampler.tick, self._maybe_sync):
            self._chore_guard(f"heartbeat chore {chore.__name__}", chore)

    def _publish_heartbeat(self):
        self._publish(heartbeat=now_iso())

    def _maybe_sync(self):
        if not self._sync_interval_sec:
            return
        if time.monotonic() - self._last_sync < self._sync_interval_sec:
            return
        self._last_sync = time.monotonic()
        self._sync()

    def _sync(self):
        self._chore_guard(
            "experiment log sync",
            self._storage.sync_log_to_remote,
            self.app_name,
            self.id,
            get_writer_id(),
        )


def _finalize_open_runs():
    """Never leave a run claiming ``running`` just because nobody finished it.

    Only this process's runs: a forked child exiting normally must not finalize
    — and so mark failed — the parent's still-running run.
    """
    for run in list(reversed(context.open_runs())):
        try:
            run.finish(exit_code=ABANDONED_EXIT_CODE)
        except Exception:
            _LOGGER.debug("Failed to finalize an abandoned run", exc_info=True)


atexit.register(_finalize_open_runs)
