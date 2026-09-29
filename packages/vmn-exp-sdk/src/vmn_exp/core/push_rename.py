"""Rename-on-collision for ``vmn exp push``.

A local run whose name the remote holds for another run is renamed on *both*
sides, so the local and remote verstr stay equal (a name-mapping ledger would
list the run twice and break log shipping). The new name is the ``.rN`` above
every local and remote name of the run's code, so it keeps the
``<code_verstr>.`` prefix and code-object ownership survives the rename.

Steps: claim the new name remotely (the run identity is the claim token), then
rename locally (``verstr``/``renamed_from`` in the metadata, the directory, the
children's ``parent`` and the ledger entry), then push under the new name. The
name being claimed is kept in the ledger as ``pending_target``, so a crash
between the claim and the local move resumes with the same name.

Only finished (``succeeded``/``failed``) and never-run (``created``) runs are
renamed. A running or stuck run is still being written under its name; a run a
local model version references, or a sweep's outer run (its trial slots are
keyed by its name), would be orphaned by a rename. Those are skipped.
"""
import os

from vmn_exp.core.push_identity import run_identity
from vmn_exp.core.push_run import COLLISION, FAILED, NEW, Outcome, push_run
from vmn_exp.core.status import (
    RUNNING, STUCK, derive_status, load_run_state, run_state_observed_at,
)
from vmn_exp.core.writer import _run_verstr_candidates, _taken_verstrs

SKIPPED = "skipped"
_FRESH, _OURS = "fresh", "ours"
_MAX_CLAIM_ATTEMPTS = 20


def local_status(local, app_name, verstr):
    """The derived status of a local run."""
    state = load_run_state(local, app_name, verstr)
    observed_at = run_state_observed_at(local, app_name, verstr)
    return derive_status(state, observed_at=observed_at)


def push_or_rename(local, target, app_name, verstr, ledger, code,
                   registered=frozenset()):
    """:func:`push_run`, renaming the run on a collision. *registered* holds
    the ``(app, verstr)`` pairs local model versions reference. A renamed
    run's :class:`Outcome` carries ``renamed_from``; a refused rename is
    :data:`SKIPPED` with the reason as ``detail``."""
    outcome = push_run(local, target, app_name, verstr, ledger, code)
    if outcome.status != COLLISION:
        return outcome
    meta = local.load_metadata(app_name, verstr)
    refusal = rename_refusal(local, app_name, verstr, meta, registered)
    if refusal:
        return Outcome(verstr, SKIPPED, refusal)
    try:
        new, fresh = _claim_new_name(local, target, app_name, verstr, meta, ledger, code)
        _move_local(local, app_name, verstr, new, ledger)
    except Exception as e:
        return Outcome(verstr, FAILED, f"rename: {e or type(e).__name__}")
    outcome = push_run(local, target, app_name, new, ledger, code)
    if fresh and outcome.status != FAILED:
        outcome.status = NEW
    outcome.renamed_from = verstr
    return outcome


def rename_refusal(local, app_name, verstr, meta, registered):
    """Why run *verstr* must keep its name, or None."""
    if meta.get("sweep"):
        return "sweep outer run collides"
    if (app_name, verstr) in registered:
        return "registered model run collides: rename refused"
    status = local_status(local, app_name, verstr)
    if status in (RUNNING, STUCK):
        return f"{status} run collides: finish the run first"
    return None


def rename_target(local, target, app_name, code_verstr):
    """The ``<code_verstr>.rN`` above every local and remote run name of it."""
    taken = (_taken_verstrs(local, app_name, code_verstr)
             | _taken_verstrs(target, app_name, code_verstr) | {code_verstr})
    return next(_run_verstr_candidates(code_verstr, taken, None))


def _claim_new_name(local, target, app_name, verstr, meta, ledger, code):
    """``(new name, whether this call created it)``, claimed remotely."""
    identity = run_identity(app_name, meta)
    _, patches = local.load_record(app_name, verstr)
    claim = _Claim(target, app_name, verstr, meta, patches or {}, identity)
    pending = (ledger.get(verstr) or {}).get("pending_target")
    how = claim.take(pending) if pending else None
    for _ in range(_MAX_CLAIM_ATTEMPTS):
        if how:
            break
        pending = rename_target(local, target, app_name, meta["code_verstr"])
        ledger.put(verstr, {"identity": identity, "pending_target": pending,
                            "complete": False})
        how = claim.take(pending)
    if not how:
        raise RuntimeError("no free name to rename the run to")
    if how == _FRESH and meta.get("code"):
        code.recheck(meta["code"])
    return pending, how == _FRESH


class _Claim:
    def __init__(self, target, app_name, verstr, meta, patches, identity):
        self._target, self._app = target, app_name
        self._verstr, self._meta, self._patches = verstr, meta, patches
        self._identity = identity

    def take(self, name):
        """:data:`_FRESH`, :data:`_OURS` (an earlier claim of this run) or None."""
        renamed = dict(self._meta, verstr=name, renamed_from=self._verstr)
        if self._target.create_exclusive(self._app, name, renamed, self._patches,
                                         claim_token=self._identity):
            return _FRESH
        remote = self._target.load_metadata(self._app, name)
        if remote is not None and run_identity(self._app, remote) == self._identity:
            return _OURS
        return None


def _move_local(local, app_name, old, new, ledger):
    local.update_metadata(app_name, old, {"verstr": new, "renamed_from": old})
    os.rename(local._snapshot_dir(app_name, old), local._snapshot_dir(app_name, new))
    for meta in local.list_snapshots(app_name):
        if meta.get("parent") == old:
            local.update_metadata(app_name, meta["verstr"], {"parent": new})
    entry = ledger.get(old) or {}
    entry.pop("pending_target", None)
    ledger.put(new, entry)
    ledger.delete(old)
