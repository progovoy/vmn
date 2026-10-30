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


def save_unless_finished_by_another(side, app_name, verstr, filename, state):
    """:func:`compare_and_save` of *state*, kept off a run another attempt
    (than ``state["attempt"]``) has finished; whether it was written."""
    attempt = state.get("attempt")

    def update(stored):
        return None if finished_by_another(stored, attempt) else state

    return compare_and_save(side, app_name, verstr, filename, update) is not None


def compare_and_save(side, app_name, verstr, filename, update):
    """Write ``update(stored state)`` (a mapping) while the stored state is
    still the one it was computed from; the state written, or None when
    *update* returned None. *update* may also raise to refuse.

    A store without version tokens (a caller's own) writes unconditionally.
    """
    for _ in range(_ROUNDS):
        stored, token = _load(side, app_name, verstr, filename)
        state = update(stored)
        if state is None:
            return None
        data = yaml.dump(state, sort_keys=False)
        if save_if_match(side, (app_name, verstr, filename), data, token)[0]:
            return state
    raise StateContendedError(f"the {filename} of {verstr} kept changing under every write")


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
