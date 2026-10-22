#!/usr/bin/env python3
"""The write side of an experiment record: the primitives that shape it.

``core.experiment_log`` folds an experiment log for readers; this is its mirror
image. Everything here knows the *shape* of an experiment record — the log entry,
the per-writer JSONL, ``run_state.yml``, the artifact digest, the ``.rN`` verstr
suffix — and nothing about git, argparse or a storage implementation. Storage is
duck-typed (``save_file``/``append_log_entry``/``save_artifact_file``/``exists``/
``list_snapshots``), so the CLI, the ``vmn_exp.sdk`` SDK and a test double
all drive the same code.

That is what lets ``vmn_exp/sdk/`` be lifted into its own distribution:
it shares these primitives with ``version_stamp/cli/experiment.py`` instead of
importing them upward out of it.
"""
import os
import socket

import yaml

from vmn_exp._base import get_repo_lock, now_iso, sha256_file  # noqa: F401
from vmn_exp._base import valid_path_component
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.children import mark_parent
from vmn_exp.core.metric_compact import note_points
from vmn_exp.core.metric_entries import (
    is_metric_entry,
    record_metric_entries,
    split_metric_entries,
)
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core import run_hint
from vmn_exp.core.record_format import stamped
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.streams import clean_writer_id, process_owner, stream_key
from vmn_exp.core.values import sanitize_entry
from vmn_exp.storage.files import user_artifact_path

# Storage params an app's conf.yml may supply (param -> conf key).
_STORAGE_CONF_KEYS = {
    "store": "uri",
    "bucket": "bucket",
    "prefix": "prefix",
    "endpoint_url": "endpoint_url",
    "experiment_dir": "experiment_dir",
    "writer_id": "writer_id",
}

WRITER_ID_ENV = "VMN_WRITER_ID"
OFFLINE_ENV = "VMN_EXP_OFFLINE"
_TRUE_VALUES = ("1", "true", "yes", "on")

# Storage params a pod can set without a conf.yml (see merge_env_into_params).
STORAGE_ENV = {
    "store": "VMN_EXPERIMENT_STORE",
    "bucket": "VMN_EXPERIMENT_BUCKET",
    "prefix": "VMN_EXPERIMENT_PREFIX",
    "endpoint_url": "VMN_EXPERIMENT_ENDPOINT_URL",
}


def offline_mode():
    """Whether ``VMN_EXP_OFFLINE`` asks to record to the local root only."""
    return os.environ.get(OFFLINE_ENV, "").strip().lower() in _TRUE_VALUES


_WRITER_ID = None


def get_writer_id(conf_writer_id=None):
    """Return a unique writer identifier for concurrent-safe log writes.

    Priority: VMN_WRITER_ID env > conf_writer_id > HOSTNAME env > socket.gethostname().
    Cached for the process lifetime. A ``~`` (the stream key separator,
    :mod:`vmn_exp.core.streams`) is replaced.
    """
    global _WRITER_ID
    if _WRITER_ID is None:
        _WRITER_ID = clean_writer_id(
            os.environ.get(WRITER_ID_ENV)
            or conf_writer_id
            or os.environ.get("HOSTNAME")
            or socket.gethostname()
        )
    return _WRITER_ID


def own_stream(storage, app_name, verstr):
    """The stream this process appends to in *verstr*: ``<writer id>~<owner>``,
    the owner the one *storage* names for the record (its local copy's), else
    this process's. Resolved per call — a compacted stream is never appended
    to again, so its owner moves on."""
    owner_for = getattr(storage, "stream_owner", None)
    owner = owner_for(app_name, verstr, get_writer_id()) if owner_for else None
    return stream_key(get_writer_id(), owner or process_owner())


def set_default_writer_id(writer_id):
    """Make *writer_id* the process's writer id unless ``VMN_WRITER_ID`` names one
    (a server's own edits, whatever an earlier call cached)."""
    global _WRITER_ID
    _WRITER_ID = clean_writer_id(os.environ.get(WRITER_ID_ENV) or writer_id)
    return _WRITER_ID


def merge_env_into_params(params):
    """Fill unset storage params from ``VMN_EXPERIMENT_*`` (flags override env).

    A pod has no conf.yml and often no checkout; the environment is how it is
    pointed at a bucket.
    """
    for key, var in STORAGE_ENV.items():
        if not params.get(key) and os.environ.get(var):
            params[key] = os.environ[var]


def merge_conf_into_params(vcs, params):
    """Fill unset storage params: CLI flags, then ``VMN_EXPERIMENT_*``, then conf.yml."""
    merge_env_into_params(params)
    exp_conf = experiment_conf(vcs)
    storage_conf = exp_conf.get("storage", {}) or {}
    for key, conf_key in _STORAGE_CONF_KEYS.items():
        if not params.get(key):
            conf_val = storage_conf.get(conf_key)
            if conf_val:
                params[key] = conf_val


# ---------------------------------------------------------------------------
# log entries
# ---------------------------------------------------------------------------


def create_log_entry(entry_type, **kwargs):
    entry = {"timestamp": now_iso(), "type": entry_type}
    entry.update(kwargs)
    return entry


def stamped_entry(entry):
    """A built *entry* (its ``type`` and fields) as :func:`create_log_entry` makes it."""
    fields = dict(entry)
    return create_log_entry(fields.pop("type"), **fields)


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
    """Append an entry to the experiment log using per-writer JSONL files —
    or, for a ``metrics`` entry, to the writer's metric stream.

    Metric values are coerced to floats first (numpy/torch scalars, numeric
    strings); non-numeric ones are dropped, and an entry left with nothing to
    record is skipped. See :mod:`vmn_exp.core.values`.
    """
    entry = sanitize_entry(entry)
    if entry is None:
        return
    if is_metric_entry(entry):
        append_metric_entries(storage, app_name, verstr, [entry])
    else:
        storage.append_log_entry(app_name, verstr, own_stream(storage, app_name, verstr), entry)


def append_metric_entries(storage, app_name, verstr, entries, inherited=False):
    """Record sanitized ``metrics`` *entries* as one block of this writer's
    metric stream (plan 12 §4.1); True when stored."""
    stream = own_stream(storage, app_name, verstr)
    writer = MetricWriter(storage, app_name, verstr, stream)
    if not record_metric_entries(writer, entries, inherited=inherited):
        return False
    points = sum(len(e.get("values") or {}) for e in entries)
    note_points(storage, app_name, verstr, stream, points)
    return True


def append_entries_to_log(storage, app_name, verstr, entries):
    """Append already-sanitized *entries* in one write where the backend can;
    ``metrics`` entries go to the metric stream.

    A duck-typed backend without ``append_log_entries`` gets them one by one.
    """
    metrics, entries = split_metric_entries(entries)
    if metrics and not append_metric_entries(storage, app_name, verstr, metrics):
        return False
    if not entries:
        return True
    stream = own_stream(storage, app_name, verstr)
    batch = getattr(storage, "append_log_entries", None)
    if batch is not None:
        return batch(app_name, verstr, stream, entries)
    for entry in entries:
        storage.append_log_entry(app_name, verstr, stream, entry)
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
    sync_to_remote(storage, app_name, verstr)


def sync_to_remote(storage, app_name, verstr, stream=None):
    """Ship the record copy's new log lines, then its new metric blocks,
    where the backend syncs them (*stream*: this process's, by default)."""
    stream = stream or own_stream(storage, app_name, verstr)
    for method in ("sync_log_to_remote", "sync_metrics_to_remote"):
        sync = getattr(storage, method, None)
        if sync is not None:
            sync(app_name, verstr, stream)


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
    """Compute sha256 and size for an artifact file, stored under its basename."""
    return {
        "path": user_artifact_path(os.path.basename(path)),
        "size": os.path.getsize(path),
        "sha256": sha256_file(path),
    }


def save_artifact(storage, app_name, verstr, src_path, name=None):
    """Copy a file into the experiment record as *name* (its record-relative
    ``artifacts/…`` or ``outputs/…`` path) when given, else as
    ``artifacts/<basename>``."""
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


class RunExistsError(FileExistsError):
    """A run was asked for under an exact name another record already holds."""


def _taken_verstrs(storage, app_name, code_verstr, suffix=None):
    """Names that could collide with a new run of *code_verstr* — names
    only, never a parse of every metadata.yml.

    Scoped to *code_verstr*'s own runs when the backend can list those
    alone (an app that stamped many code versions would otherwise list every
    run of every one of them), and with a *suffix* to the names under
    ``<code_verstr>.<suffix>`` alone: a writer's runs never collide with the
    code version's other runs, however many it has.
    """
    if hasattr(storage, "list_run_verstrs"):
        scope = f"{code_verstr}.{suffix}" if suffix else code_verstr
        return set(storage.list_run_verstrs(app_name, scope))
    if hasattr(storage, "list_verstrs"):
        return set(storage.list_verstrs(app_name))
    return {m.get("verstr", "") for m in storage.list_snapshots(app_name)}


def default_run_suffix():
    """The suffix a new run's name carries unless told otherwise: the pod's
    VMN_WRITER_ID (K8s mode), else the writer id when recording offline — an
    offline run is named without seeing the remote, so ``.rN`` could collide
    with another host's — else None (``.rN``)."""
    writer_id = os.environ.get(WRITER_ID_ENV)
    if writer_id:
        return writer_id
    return get_writer_id() if offline_mode() else None


def _run_verstr_candidates(code_verstr, taken, suffix):
    """Free-looking names for a new run, in allocation order.

    With a *suffix* the name is ``<code_verstr>.<suffix>[.N]``; otherwise it
    is the ``.rN`` after the highest existing run of this code.
    """
    if suffix:
        base = code_verstr + "." + suffix
        names = (
            base if i == 1 else f"{base}.{i}" for i in range(1, _MAX_RUN_CANDIDATES)
        )
    else:
        runs = [run_hint.run_number(code_verstr, v) for v in taken]
        first = max((n for n in runs if n), default=0) + 1
        names = (
            run_hint.run_name(code_verstr, n)
            for n in range(first, first + _MAX_RUN_CANDIDATES)
        )
    return (name for name in names if name not in taken)


def _claim(storage, app_name, verstr, metadata, patches):
    """Create the record unless *verstr* is taken; a child's own claim also
    marks it in its parent's record (best-effort)."""
    metadata = stamped(metadata)
    if hasattr(storage, "create_exclusive"):
        if not storage.create_exclusive(app_name, verstr, metadata, patches):
            return False
    elif storage.exists(app_name, verstr):
        return False
    else:
        storage.save(app_name, verstr, metadata, patches)
    mark_parent(storage, app_name, metadata)
    return True


def claim_record(storage, app_name, verstr, metadata):
    """Atomically claim a specific *verstr* by writing *metadata* under it.

    Returns ``True`` when the record was newly created, ``False`` when *verstr*
    was already taken.  Use this when the verstr is known in advance
    (importers, registry) — normal experiment runs use :func:`create_run`.
    """
    return _claim(storage, app_name, verstr, metadata, {})


def check_run_id(code_verstr, run_id):
    """Refuse a *run_id* that is not ``<code_verstr>.<suffix>`` record name."""
    suffix = run_id[len(code_verstr) + 1:] if run_id.startswith(code_verstr + ".") else ""
    if not suffix or not valid_path_component(run_id):
        raise ValueError(
            f"run_id {run_id!r} must be a run of the code version it records: "
            f"'{code_verstr}.<suffix>'"
        )


def claim_exact(storage, app_name, run_id, make_record):
    """Create the record under exactly *run_id* (no listing); RunExistsError
    when another record holds the name."""
    if not _claim_made(storage, app_name, run_id, make_record):
        raise RunExistsError(f"Run '{run_id}' already exists for {app_name}")
    return run_id


_DEFAULT_SUFFIX = object()


def allocate_run_verstr(storage, app_name, code_verstr, make_record=None,
                        suffix=_DEFAULT_SUFFIX):
    """Return the verstr for a new experiment run.

    *suffix*: ``<code_verstr>.<suffix>[.N]`` names, listing only the names
    under ``<code_verstr>.<suffix>``; None for plain ``.rN`` names whatever
    the environment says; by default :func:`default_run_suffix`.

    With *make_record* — ``verstr -> (metadata, patches)`` — the name is also
    claimed: the record is created atomically under it, and a name another
    host claimed first (a shared bucket or directory) is skipped. Without it
    the first free-looking name is returned unclaimed.

    A ``.rN`` claim lists the code version's runs once per process: later
    ones claim upward from the highest this process claimed
    (:mod:`vmn_exp.core.run_hint`) while that run still exists, and list
    again after :data:`_HINT_MISSES` names in a row were taken.
    """
    if suffix is _DEFAULT_SUFFIX:
        suffix = default_run_suffix()
    hint = None if suffix or make_record is None else run_hint.hint_key(
        storage, app_name, code_verstr)
    if hint is not None:
        claimed = _claim_from_hint(storage, app_name, code_verstr, make_record, hint)
        if claimed:
            return claimed
    taken = _taken_verstrs(storage, app_name, code_verstr, suffix)
    for candidate in _run_verstr_candidates(code_verstr, taken, suffix):
        if make_record is None:
            if not storage.exists(app_name, candidate):
                return candidate
            continue
        if _claim_made(storage, app_name, candidate, make_record):
            if hint is not None:
                run_hint.note(hint, run_hint.run_number(code_verstr, candidate))
            return candidate
    raise RuntimeError("Could not allocate experiment verstr")


_HINT_MISSES = 3


def _claim_made(storage, app_name, verstr, make_record):
    metadata, patches = make_record(verstr)
    return _claim(storage, app_name, verstr, metadata, patches)


def _claim_from_hint(storage, app_name, code_verstr, make_record, hint):
    """The ``.rN`` claimed upward from *hint*'s run, else None (no hint, its
    run is gone, or the next names were all taken)."""
    last = run_hint.get(hint)
    if last is None or not storage.exists(app_name, run_hint.run_name(code_verstr, last)):
        return None
    for n in range(last + 1, last + 1 + _HINT_MISSES):
        candidate = run_hint.run_name(code_verstr, n)
        if _claim_made(storage, app_name, candidate, make_record):
            run_hint.note(hint, n)
            return candidate
    return None


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
    env=None,
    features=None,
    run_id=None,
):
    """Claim a run verstr for *template* and write the record and its create entry.

    *run_id* names the run exactly (``<code_verstr>.<suffix>``): it is created
    with one exclusive create and no listing, RunExistsError when taken.

    *template* is the record's metadata minus its identity: each claim attempt
    stamps a copy with the candidate verstr, ``code_verstr``, parent and name.

    *env* is a full environment dict (from ``capture_env()`` or
    ``env_from_interpreter()``).  When provided, a compact summary is embedded
    in the metadata under ``"env"`` and the full dict is written to ``env.yml``
    next to the record.  All env-related failures are best-effort: a write
    error never prevents the run from being created.

    *features*, a ``features`` log entry (``core.features.build_features_entry``),
    is written right after the create entry, in the same write.
    """
    effective_template = template
    if env is not None:
        try:
            from vmn_exp.core.env import env_summary

            effective_template = dict(template, env=env_summary(env))
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "vmn: could not compute env summary — env key omitted from metadata"
            )

    def make_record(verstr):
        metadata = dict(effective_template, verstr=verstr, code_verstr=code_verstr)
        attach_parent(metadata, parent)
        attach_name(metadata, name)
        return metadata, patches

    if run_id is None:
        verstr = allocate_run_verstr(storage, app_name, code_verstr, make_record=make_record)
    else:
        check_run_id(code_verstr, run_id)
        verstr = claim_exact(storage, app_name, run_id, make_record)

    if env is not None:
        try:
            storage.save_file(
                app_name, verstr, "env.yml", yaml.dump(env, sort_keys=False)
            )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                f"vmn: could not write env.yml for run {verstr}"
            )

    entry = create_log_entry("create", note=note)
    if create_data:
        entry.update(create_data)
    if features is None:
        append_to_log(storage, app_name, verstr, entry)
    else:
        features = {"timestamp": entry["timestamp"], **features}
        append_entries_to_log(storage, app_name, verstr,
                              [sanitize_entry(entry), sanitize_entry(features)])
    return verstr
