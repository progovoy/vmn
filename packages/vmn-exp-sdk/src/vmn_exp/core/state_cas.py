#!/usr/bin/env python3
"""Ending a run exactly once: compare-and-swap writes of ``run_state.yml``.

Two attempts of one run (speculative duplicates, a pod resumed next to a live
one) share its state, and only the first to end it may: a later ``finish`` or
``release`` by another attempt, or a ``finish_run`` from outside the run, must
not erase the winner's exit code. So a final write reads the stored state with
its version token (S3/Azure ETag, GCS generation, a local content hash) and
writes only while the token still matches; refused, it reads again and decides
again. Two finishers racing cannot both land.
"""
import uuid

import yaml

from vmn_exp import _base
from vmn_exp.storage.cached import CachedSnapshotStorage, local_side

# Each refusal is another writer landing in between: a live attempt's beat,
# at most once per interval, so a handful of rounds settles any real race.
_ROUNDS = 8


class StateContendedError(RuntimeError):
    """The state kept changing under every conditional write."""


def split_storage(storage, app_name, verstr):
    """``(inline, remote target or None)`` of *storage* for one run's state
    writes; the target is called for the store to upload to (None: none yet).

    A local-first cache with a remote is split into its local side and its
    remote — written only once the remote is known to hold this run
    (:meth:`CachedSnapshotStorage.remote_for`, whose check may be a GET, so it
    runs in the background too). A store that is remote only is written
    entirely in the background; anything else (a local store, or a caller's
    own wrapper) is written inline, as given.
    """
    local = local_side(storage)
    if not getattr(storage, "is_remote", lambda: False)():
        return local, None
    if isinstance(storage, CachedSnapshotStorage):
        return local, lambda: storage.remote_for(app_name, verstr)
    return None, lambda: storage


def finished_by_another(stored, attempt):
    """Whether *stored* is a final state that *attempt* did not write."""
    return bool(stored) and stored.get("state") == "finished" and (
        stored.get("attempt") != attempt
    )


def new_attempt_id():
    """A new id of one process's attempt at a run (its state's ``attempt``)."""
    return uuid.uuid4().hex[:12]


def compare_and_save(side, app_name, verstr, filename, update):
    """Write ``update(stored state)`` (a mapping) while the stored state is
    still the one it was computed from; the state written, or None when
    *update* returned None. *update* may also raise to refuse.

    A store without version tokens (a caller's own) writes unconditionally.
    """
    return compare_and_save_token(side, (app_name, verstr, filename), update)[0]


def compare_and_save_token(side, where, update, seed=None, dumped=None):
    """:func:`compare_and_save` at *where*, returning ``(state written or
    None, its token)``. *seed* — ``(stored state, token)`` known without a
    read, as of the caller's own last write — is the first round's: while
    its token is current the write is one conditional save, no read.
    *dumped* — ``(state, its YAML)`` — saves dumping a state *update* returns
    as is."""
    for _ in range(_ROUNDS):
        stored, token = seed or _load(side, *where)
        seed = None
        state = update(stored)
        if state is None:
            return None, None
        data = dumped[1] if dumped and state is dumped[0] else dump_state(state)
        written, token = save_if_match(side, where, data, token)
        if written:
            return state, token
    raise StateContendedError(f"the {where[2]} of {where[1]} kept changing under every write")


def dump_state(state):
    """The YAML a run state is stored as."""
    return yaml.dump(state, sort_keys=False)


def pull_record(storage, inline, app_name, verstr):
    """Fetch a record only *storage*'s remote holds into *inline*, its local
    side; whether *inline* holds the record now (*inline* being *storage*
    itself: nothing to fetch, it does)."""
    if inline is None or inline is storage:
        return inline is not None
    if inline.exists(app_name, verstr):
        return True
    storage.load_record(app_name, verstr)
    return inline.exists(app_name, verstr)


def _load(side, app_name, verstr, filename):
    load = getattr(side, "load_file_with_token", None)
    raw, token = load(app_name, verstr, filename) if load else (
        side.load_file(app_name, verstr, filename), None)
    state = _base.yaml_safe_load(raw) if raw else None
    return (state if isinstance(state, dict) else {}), token


def save_if_match(side, where, data, etag=None):
    """``(written, token)`` of writing *data*; a store without
    ``save_file_if_match`` (a caller's own) writes unconditionally."""
    save = getattr(side, "save_file_if_match", None)
    if save is None:
        side.save_file(*where, data)
        return True, None
    return save(*where, data, etag)
