#!/usr/bin/env python3
"""The write side of an experiment record: the primitives that shape it.

``core.experiment_log`` folds an experiment log for readers; this is its mirror
image. Everything here knows the *shape* of an experiment record — the log entry,
the per-writer JSONL, ``run_state.yml``, the artifact digest, the ``.rN`` verstr
suffix — and nothing about git, argparse or a storage implementation. Storage is
duck-typed (``save_file``/``append_log_entry``/``save_artifact_file``/``exists``/
``list_snapshots``), so the CLI, the ``version_stamp.exp`` SDK and a test double
all drive the same code.

That is what lets ``version_stamp/exp/`` be lifted into its own distribution:
it shares these primitives with ``version_stamp/cli/experiment.py`` instead of
importing them upward out of it.
"""
import os
import socket

import yaml
from filelock import FileLock

from version_stamp.core.constants import LOCK_FILE_ENV, LOCK_FILENAME
from version_stamp.core.experiment_status import RUN_STATE_FILE
from version_stamp.core.experiment_values import sanitize_entry
from version_stamp.core.utils import now_iso, sha256_file

# Storage conf keys that an app's conf.yml may supply, and the CLI defaults that
# count as "unset" for merging purposes.
_STORAGE_CONF_KEYS = (
    "bucket",
    "backend",
    "prefix",
    "endpoint_url",
    "experiment_dir",
    "writer_id",
)
_DEFAULT_PARAM_VALUES = ("local", "vmn-experiments")

WRITER_ID_ENV = "VMN_WRITER_ID"

# Storage params a pod can set without a conf.yml (see merge_env_into_params).
STORAGE_ENV = {
    "bucket": "VMN_EXPERIMENT_BUCKET",
    "prefix": "VMN_EXPERIMENT_PREFIX",
    "endpoint_url": "VMN_EXPERIMENT_ENDPOINT_URL",
}


def get_repo_lock(vmn_root_path):
    """The per-repo vmn lock that serializes mutations of a checkout.

    One definition for every entry point: the CLI holds it around a command, and
    ``version_stamp.exp.start_run`` holds it around the mutating create phase.
    ``$VMN_LOCK_FILE_PATH`` overrides the path for the whole process, which is
    what a user pointing vmn at a shared lock expects.
    """
    return FileLock(
        os.environ.get(LOCK_FILE_ENV)
        or os.path.join(vmn_root_path, ".vmn", LOCK_FILENAME)
    )


_WRITER_ID = None


def get_writer_id(conf_writer_id=None):
    """Return a unique writer identifier for concurrent-safe log writes.

    Priority: VMN_WRITER_ID env > conf_writer_id > HOSTNAME env > socket.gethostname().
    Cached for the process lifetime so all log entries land in the same JSONL file.
    """
    global _WRITER_ID
    if _WRITER_ID is None:
        _WRITER_ID = (
            os.environ.get(WRITER_ID_ENV)
            or conf_writer_id
            or os.environ.get("HOSTNAME")
            or socket.gethostname()
        )
    return _WRITER_ID


def _is_unset(params, key):
    return not params.get(key) or params[key] in _DEFAULT_PARAM_VALUES


def merge_env_into_params(params):
    """Fill unset storage params from ``VMN_EXPERIMENT_*`` (flags override env).

    A pod has no conf.yml and often no checkout; the environment is how it is
    pointed at a bucket.
    """
    for key, var in STORAGE_ENV.items():
        if _is_unset(params, key) and os.environ.get(var):
            params[key] = os.environ[var]


def merge_conf_into_params(vcs, params):
    """Fill unset storage params: CLI flags, then ``VMN_EXPERIMENT_*``, then conf.yml."""
    merge_env_into_params(params)
    exp_conf = getattr(vcs, "experiment", None) or {}
    storage_conf = (
        exp_conf.get("storage", {}) or getattr(vcs, "snapshot_storage", None) or {}
    )
    for key in _STORAGE_CONF_KEYS:
        if _is_unset(params, key):
            conf_val = storage_conf.get(key)
            if conf_val:
                params[key] = conf_val


# ---------------------------------------------------------------------------
# log entries
# ---------------------------------------------------------------------------


def create_log_entry(entry_type, **kwargs):
    entry = {"timestamp": now_iso(), "type": entry_type}
    entry.update(kwargs)
    return entry


def append_to_log(storage, app_name, verstr, entry):
    """Append an entry to the experiment log using per-writer JSONL files.

    Metric values are coerced to floats first (numpy/torch scalars, numeric
    strings); non-numeric ones are dropped, and an entry left with nothing to
    record is skipped. See :mod:`version_stamp.core.experiment_values`.
    """
    entry = sanitize_entry(entry)
    if entry is not None:
        storage.append_log_entry(app_name, verstr, get_writer_id(), entry)


def save_log(storage, app_name, verstr, log):
    """Save experiment log to storage. Legacy: prefer append_to_log for new code."""
    storage.save_file(app_name, verstr, "log.yml", yaml.dump(log, sort_keys=False))


# ---------------------------------------------------------------------------
# run state
# ---------------------------------------------------------------------------


def save_run_state(storage, app_name, verstr, run_state, **updates):
    """Apply ``updates`` to the run state and publish it."""
    run_state.update(updates)
    storage.save_file(
        app_name, verstr, RUN_STATE_FILE, yaml.dump(run_state, sort_keys=False)
    )


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


def compute_artifact_info(path):
    """Compute sha256 and size for an artifact file."""
    return {
        "path": os.path.basename(path),
        "size": os.path.getsize(path),
        "sha256": sha256_file(path),
    }


def save_artifact(storage, app_name, verstr, src_path):
    """Copy an artifact file into the experiment directory."""
    storage.save_artifact_file(app_name, verstr, src_path)


# ---------------------------------------------------------------------------
# identity of a new record
# ---------------------------------------------------------------------------


def attach_parent(metadata, parent):
    """Record the experiment that launched this one — never the run itself."""
    if parent and parent != metadata["verstr"]:
        metadata["parent"] = parent


_MAX_RUN_CANDIDATES = 100000


def _taken_verstrs(storage, app_name):
    """Names already used — names only, never a parse of every metadata.yml."""
    if hasattr(storage, "list_verstrs"):
        return set(storage.list_verstrs(app_name))
    return {m.get("verstr", "") for m in storage.list_snapshots(app_name)}


def _run_verstr_candidates(code_verstr, taken):
    """Free-looking names for a new run, in allocation order.

    With VMN_WRITER_ID (K8s mode) the name carries the pod-unique suffix;
    otherwise it is the ``.rN`` after the highest existing run of this code.
    """
    writer_id = os.environ.get(WRITER_ID_ENV)
    if writer_id:
        base = code_verstr + "." + writer_id
        names = (
            base if i == 1 else f"{base}.{i}" for i in range(1, _MAX_RUN_CANDIDATES)
        )
    else:
        runs = [1] if code_verstr in taken else []
        for v in taken:
            suffix = v[len(code_verstr) + 2 :]
            if v.startswith(code_verstr + ".r") and suffix.isdigit():
                runs.append(int(suffix))
        first = max(runs) + 1 if runs else 1
        names = (
            code_verstr if n == 1 else f"{code_verstr}.r{n}"
            for n in range(first, first + _MAX_RUN_CANDIDATES)
        )
    return (name for name in names if name not in taken)


def _claim(storage, app_name, verstr, metadata, patches):
    if hasattr(storage, "create_exclusive"):
        return storage.create_exclusive(app_name, verstr, metadata, patches)
    if storage.exists(app_name, verstr):
        return False
    storage.save(app_name, verstr, metadata, patches)
    return True


def allocate_run_verstr(storage, app_name, code_verstr, make_record=None):
    """Return the verstr for a new experiment run.

    With *make_record* — ``verstr -> (metadata, patches)`` — the name is also
    claimed: the record is created atomically under it, and a name another
    host claimed first (a shared bucket or directory) is skipped. Without it
    the first free-looking name is returned unclaimed.
    """
    taken = _taken_verstrs(storage, app_name)
    for candidate in _run_verstr_candidates(code_verstr, taken):
        if make_record is None:
            if not storage.exists(app_name, candidate):
                return candidate
            continue
        metadata, patches = make_record(candidate)
        if _claim(storage, app_name, candidate, metadata, patches):
            return candidate
    raise RuntimeError("Could not allocate experiment verstr")
