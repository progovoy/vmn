"""Trial slots, claimed with ``create_exclusive`` — no server, no lock.

Every slot is a record of the reserved pseudo-app ``vmn-sweeps``, named
``<app>~<sweep verstr>.t<N>`` (``/`` in the app becomes ``~``). Creating one is
atomic on every backend (``O_EXCL`` mkdir locally, a conditional PUT on object
stores), so exactly one agent owns trial N even when many share an NFS dir or a
bucket. The loser re-lists and tries the next free index. A retry of trial N
claims ``....t<N>.a<K>`` the same way, so two retriers never re-run it twice.

A claim's metadata holds the trial's params (what a bayes agent drew), the
agent and, once created, the trial's run verstr. Claims are never deleted, so
an index is never handed out twice, even when its agent died mid-claim.
"""
import re

from vmn_exp._base import now_iso
from vmn_exp.core.sweep.spec import trial_limit
from vmn_exp.core.sweep.suggest import suggest
from vmn_exp.core.writer import claim_record, get_writer_id

SWEEP_APP = "vmn-sweeps"
_MAX_ATTEMPTS = 1000
_SLOT = re.compile(r"^\.t(\d+)(?:\.a(\d+))?$")


def sweep_key(app_name, sweep_verstr):
    return f"{app_name.replace('/', '~')}~{sweep_verstr}"


def claim_next_trial(storage, app_name, sweep_verstr, spec, agent=None, history=None):
    """Claim the lowest free trial index: ``{trial, attempt, params, ...}``, or
    None once the sweep's trial limit is reached. *history* is a callable
    returning ``[(params, value)]``, read only for bayes suggestions."""
    limit = trial_limit(spec)
    for _ in range(_MAX_ATTEMPTS):
        taken = {trial for trial, _attempt in _slots(storage, app_name, sweep_verstr)}
        n = max(taken, default=-1) + 1
        if limit is not None and n >= limit:
            return None
        past = history() if history and spec["method"] == "bayes" else ()
        claim = _claim(storage, app_name, sweep_verstr, n, 0, suggest(spec, n, past), agent)
        if claim is not None:
            return claim
    raise RuntimeError(f"Could not claim a trial of sweep {sweep_verstr}")


def claim_retry(storage, app_name, sweep_verstr, trial, agent=None, attempt=None):
    """Claim a new attempt at *trial*, with the original params.

    With *attempt*, claim exactly that one — None when another agent already
    did, which is how an agent that saw attempt K fail avoids a duplicate
    retry. Without, claim the next free attempt. None when the trial was never
    claimed.
    """
    original = _load(storage, _record(app_name, sweep_verstr, trial, 0))
    if original is None:
        return None
    if attempt is not None:
        return _claim(storage, app_name, sweep_verstr, trial, attempt,
                      original["params"], agent)
    for _ in range(_MAX_ATTEMPTS):
        attempts = [a for t, a in _slots(storage, app_name, sweep_verstr) if t == trial]
        attempt = max(attempts, default=0) + 1
        claim = _claim(storage, app_name, sweep_verstr, trial, attempt,
                       original["params"], agent)
        if claim is not None:
            return claim
    raise RuntimeError(f"Could not claim a retry of trial {trial} of {sweep_verstr}")


def attach_run(storage, claim, run_verstr):
    """Record which run carries out *claim*."""
    storage.update_metadata(SWEEP_APP, claim["verstr"], {"run": run_verstr})


def list_claims(storage, app_name, sweep_verstr):
    """Every complete claim of the sweep, ordered by (trial, attempt)."""
    claims = []
    for trial, attempt in sorted(_slots(storage, app_name, sweep_verstr)):
        meta = _load(storage, _record(app_name, sweep_verstr, trial, attempt))
        if meta is not None:
            claims.append(meta)
    return claims


def _claim(storage, app_name, sweep_verstr, trial, attempt, params, agent):
    name = _record(app_name, sweep_verstr, trial, attempt)
    metadata = {
        "verstr": name,
        "app": app_name,
        "sweep": sweep_verstr,
        "trial": trial,
        "attempt": attempt,
        "params": params,
        "agent": agent or get_writer_id(),
        "timestamp": now_iso(),
    }
    return metadata if claim_record(storage, SWEEP_APP, name, metadata) else None


def _record(app_name, sweep_verstr, trial, attempt):
    name = f"{sweep_key(app_name, sweep_verstr)}.t{trial}"
    return f"{name}.a{attempt}" if attempt else name


def _slots(storage, app_name, sweep_verstr):
    """``{(trial, attempt)}`` of every slot, in-flight claims included."""
    prefix = sweep_key(app_name, sweep_verstr)
    list_names = getattr(storage, "list_record_names", storage.list_verstrs)
    slots = set()
    for name in list_names(SWEEP_APP):
        match = _SLOT.match(name[len(prefix):]) if name.startswith(prefix) else None
        if match:
            slots.add((int(match.group(1)), int(match.group(2) or 0)))
    return slots


def _load(storage, name):
    return storage.load_metadata(SWEEP_APP, name)
