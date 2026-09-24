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


def create_tags_entry(tags=None, remove=None):
    """A ``tags`` log entry: set *tags* (values stored as strings), drop *remove*.

    Tags are mutable: readers fold these entries per key, last write wins, and
    a removal is a write like any other.
    """
    tags, remove = dict(tags or {}), list(remove or [])
    for key in list(tags) + remove:
        if not isinstance(key, str) or not key:
            raise ValueError(f"Tag keys must be non-empty strings, got {key!r}")
    if not tags and not remove:
        raise ValueError("Nothing to tag: give tags to set or keys to remove")
    entry = create_log_entry("tags", set={k: str(v) for k, v in tags.items()})
    if remove:
        entry["remove"] = remove
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


def append_entries_to_log(storage, app_name, verstr, entries):
    """Append already-sanitized *entries* in one write where the backend can.

    A duck-typed backend without ``append_log_entries`` gets them one by one.
    """
    writer = get_writer_id()
    batch = getattr(storage, "append_log_entries", None)
    if batch is not None:
        return batch(app_name, verstr, writer, entries)
    for entry in entries:
        storage.append_log_entry(app_name, verstr, writer, entry)
    return True


def flush_log(storage, app_name, verstr):
    """Ship this writer's just-appended log entries to the remote right away.

    Storage such as :class:`CachedSnapshotStorage` only ships new log bytes
    when something calls ``sync_log_to_remote`` -- ordinarily a live run's
    heartbeat loop (`exp run`'s supervisor, the SDK), on its own schedule.
    A one-shot caller (``tag``, ``add --note``, ``create --metrics`` on a run
    with no such loop) has no heartbeat left to do that later, so it must call
    this right after appending. Backends without the method (a plain S3
    remote, which has nothing to sync) are left alone.
    """
    sync = getattr(storage, "sync_log_to_remote", None)
    if sync is not None:
        sync(app_name, verstr, get_writer_id())


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


def save_artifact(storage, app_name, verstr, src_path, name=None):
    """Copy an artifact file into the experiment directory, as *name* (a
    relative ``a/b/c`` path) when given, else under its basename."""
    if name is None:
        storage.save_artifact_file(app_name, verstr, src_path)
    else:
        storage.save_artifact_file(app_name, verstr, src_path, name=name)


# ---------------------------------------------------------------------------
# identity of a new record
# ---------------------------------------------------------------------------


def attach_parent(metadata, parent):
    """Record the experiment that launched this one — never the run itself."""
    if parent and parent != metadata["verstr"]:
        metadata["parent"] = parent


def attach_name(metadata, name):
    """Record the run's human-readable name, when it was given one."""
    if name:
        metadata["name"] = str(name)


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


def create_run(
    storage,
    app_name,
    code_verstr,
    template,
    patches,
    note=None,
    create_data=None,
    parent=None,
    name=None,
):
    """Claim a run verstr for *template* and write the record and its create entry.

    *template* is the record's metadata minus its identity: each claim attempt
    stamps a copy with the candidate verstr, ``code_verstr``, parent and name.
    """

    def make_record(verstr):
        metadata = dict(template, verstr=verstr, code_verstr=code_verstr)
        attach_parent(metadata, parent)
        attach_name(metadata, name)
        return metadata, patches

    verstr = allocate_run_verstr(storage, app_name, code_verstr, make_record=make_record)
    entry = create_log_entry("create", note=note)
    if create_data:
        entry.update(create_data)
    append_to_log(storage, app_name, verstr, entry)
    return verstr
