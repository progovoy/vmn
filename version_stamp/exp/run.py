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
import logging
import os
import socket
import sys
import time
from types import SimpleNamespace

from version_stamp.cli.constants import INIT_FILENAME
from version_stamp.cli.experiment import (
    _append_to_log,
    _compute_artifact_info,
    _create_log_entry,
    _experiment_create_core,
    _get_experiment_storage,
    _get_writer_id,
    _merge_conf_into_params,
    _resolve_parent,
    _save_artifact,
    _save_run_state,
    get_repo_lock,
)
from version_stamp.cli.snapshot import _now_iso
from version_stamp.core import logging as vmn_logging
from version_stamp.core.constants import VMN_BE_TYPE_GIT
from version_stamp.core.experiment_status import DEFAULT_HEARTBEAT_INTERVAL_SEC
from version_stamp.core.utils import resolve_root_path
from version_stamp.exp import APP_NAME_ENV, _resolve_app_name
from version_stamp.exp.heartbeat import Heartbeat

# Stdlib logging, not VMN_LOGGER: an SDK user never calls init_stamp_logger, and
# a library emits records rather than configuring handlers.
_LOGGER = logging.getLogger(__name__)

EXPERIMENT_ID_ENV = "VMN_EXPERIMENT_ID"

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

# Innermost-last, so `nested=True` picks the enclosing run off the end.
_OPEN_RUNS = []


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

    status = _get_repo_status(vcs, _EXPECTED_STATUS, _OPTIONAL_STATUS)
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
    _merge_conf_into_params(vcs, params)
    return _get_experiment_storage(vcs, params)


def _pick_parent(storage, app_name, parent, nested):
    """Resolve the parent experiment, following the CLI's validation policy.

    Precedence: an explicit ``parent`` (a bad one is a hard error), then the
    innermost open in-process run when ``nested``, then ``VMN_EXPERIMENT_ID``
    (a stale one is warned about and dropped — the outer run may have been
    pruned, which is no reason to fail this one).
    """
    if parent:
        resolved, err = _resolve_parent(
            storage, app_name, SimpleNamespace(parent=parent)
        )
        if err:
            raise ValueError(f"Unknown parent experiment: {parent}")
        return resolved

    if nested and _OPEN_RUNS:
        return _OPEN_RUNS[-1].id

    return _resolve_parent(storage, app_name, None)[0]


def start_run(
    app_name=None,
    note=None,
    params=None,
    parent=None,
    nested=False,
    heartbeat_interval_sec=None,
    storage=None,
):
    """Create an experiment, mark it running and return the open ``Run``.

    ``app_name=None`` resolves the app from the current checkout. Use the result
    as a context manager, or call ``finish()`` yourself.
    """
    # The reused CLI helpers log through VMN_LOGGER, which raises until something
    # initializes it — and a library must not call init_stamp_logger.
    vmn_logging.ensure_logger()
    app_name = _resolve_app_name(app_name, _stamped_apps)
    vcs = _build_vcs(app_name)

    # Cold start inits the repo and stamps a baseline, and verstr allocation
    # scans for a free `.rN` - both must not race a concurrent vmn. The rest of
    # the run writes only inside its own experiment directory, so the lock is
    # scoped to creation and never held for the life of the run.
    with get_repo_lock(vcs.vmn_root_path):
        _cold_start(vcs)
        if storage is None:
            storage = _build_storage(vcs)

        resolved_parent = _pick_parent(storage, app_name, parent, nested)

        verstr, err = _experiment_create_core(
            vcs,
            storage,
            note=note,
            # Same shape as the CLI's `-f file` params, so _get_latest_metrics
            # and `exp diff` pick them up unchanged.
            extra_create_data={"params": dict(params)} if params else None,
            parent=resolved_parent,
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
    )
    run._open()
    return run


class Run:
    """One open experiment run: a metrics sink plus a liveness publisher."""

    def __init__(self, storage, app_name, verstr, heartbeat_interval_sec):
        self._storage = storage
        self.app_name = app_name
        self.id = verstr

        self._finished = False
        self._monotonic_start = time.monotonic()
        self._saved_env = {}

        started_at = _now_iso()
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

    # -- lifecycle ---------------------------------------------------------

    def _open(self):
        self._publish()
        self._export_env()
        _OPEN_RUNS.append(self)
        self._heartbeat.start()

    def finish(self, exit_code=0):
        """Finalize the run. Idempotent: a second call changes nothing."""
        if self._finished:
            return
        self._finished = True

        self._heartbeat.stop()
        duration = round(time.monotonic() - self._monotonic_start, 3)
        self._publish(
            state="finished",
            exit_code=exit_code,
            finished_at=_now_iso(),
            duration_sec=duration,
        )
        self._append(
            _create_log_entry(
                "run",
                command=self._state["command"],
                exit_code=exit_code,
                duration_sec=duration,
            )
        )
        self._sync()
        self._restore_env()
        if self in _OPEN_RUNS:
            _OPEN_RUNS.remove(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._finished:
            return False
        if exc is None:
            self.finish()
            return False
        self._append(
            _create_log_entry("error", exception=type(exc).__name__, message=str(exc))
        )
        self.finish(exit_code=1)
        return False  # never swallow the workload's exception

    # -- recording ---------------------------------------------------------

    def log_metric(self, key, value, step=None):
        self.log_metrics({key: value}, step=step)

    def log_metrics(self, mapping, step=None):
        entry = _create_log_entry("metrics", values=dict(mapping))
        if step is not None:
            entry["step"] = step
        self._append(entry)

    def log_params(self, mapping):
        # A `params` entry, not a rewrite of the `create` entry: the log is
        # append-only, so readers fold later params in rather than see them move.
        self._append(_create_log_entry("params", params=dict(mapping)))

    def log_note(self, text):
        self._append(_create_log_entry("note", text=text))

    def log_artifact(self, path):
        info = _compute_artifact_info(path)
        _save_artifact(self._storage, self.app_name, self.id, path)
        self._append(_create_log_entry("artifact", **info))

    # -- internals ---------------------------------------------------------

    def _append(self, entry):
        _append_to_log(self._storage, self.app_name, self.id, entry)

    def _publish(self, **updates):
        _save_run_state(self._storage, self.app_name, self.id, self._state, **updates)

    def _beat(self):
        self._publish(heartbeat=_now_iso())

    def _sync(self):
        try:
            self._storage.sync_log_to_remote(self.app_name, self.id, _get_writer_id())
        except Exception:
            _LOGGER.debug("Experiment log sync failed", exc_info=True)

    def _export_env(self):
        """Let a subprocess auto-link as an inner run, as ``vmn exp run`` does."""
        for key, value in ((EXPERIMENT_ID_ENV, self.id), (APP_NAME_ENV, self.app_name)):
            self._saved_env[key] = os.environ.get(key)
            os.environ[key] = value

    def _restore_env(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._saved_env.clear()


def _finalize_open_runs():
    """Never leave a run claiming ``running`` just because nobody finished it."""
    for run in list(reversed(_OPEN_RUNS)):
        try:
            run.finish(exit_code=ABANDONED_EXIT_CODE)
        except Exception:
            _LOGGER.debug("Failed to finalize an abandoned run", exc_info=True)


atexit.register(_finalize_open_runs)
