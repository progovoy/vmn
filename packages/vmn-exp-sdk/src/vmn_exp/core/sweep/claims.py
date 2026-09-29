"""Trial slots, claimed with ``create_exclusive`` — no server, no lock.

Every slot is a record ``t<N>`` of the sweep's own pseudo-app
``vmn-sweeps/<app>~<sweep verstr>`` (``/`` in the app becomes ``~``; the
``vmn-sweeps`` tree is reserved), so listing a sweep's slots never reads another
sweep's. Creating one is atomic on every backend (``O_EXCL`` mkdir locally, a
conditional PUT on object stores), so exactly one agent owns trial N even when
many share an NFS dir or a bucket. The loser re-lists and tries the next free
index. A retry of trial N claims ``t<N>.a<K>`` the same way, so two retriers
never re-run it twice.

A claim's metadata holds the trial's params (what a bayes agent drew), the
agent and, once created, the trial's run verstr. Claims are never deleted, so
an index is never handed out twice, even when its agent died mid-claim.
"""
import re

from vmn_exp._base import now_iso
from vmn_exp.core.sweep.spec import trial_limit
from vmn_exp.core.sweep.suggest import suggest
from vmn_exp.core.writer import claim_record, get_writer_id
from vmn_exp.storage.s3_base import parallel_map

SWEEP_APP = "vmn-sweeps"
_MAX_ATTEMPTS = 1000
_SLOT = re.compile(r"^t(\d+)(?:\.a(\d+))?$")


def claims_app(app_name, sweep_verstr):
    """The pseudo-app holding one sweep's slots."""
    return f"{SWEEP_APP}/{app_name.replace('/', '~')}~{sweep_verstr}"


def claim_next_trial(storage, app_name, sweep_verstr, spec, agent=None, history=None):
    """Claim the lowest free trial index: ``{trial, attempt, params, ...}``, or
    None once the sweep's trial limit is reached. *history* is a callable
    returning ``[(params, value)]``, read (once) only for bayes suggestions."""
    limit = trial_limit(spec)
    past = history() if history and spec["method"] == "bayes" else ()
    n = 0
    for _ in range(_MAX_ATTEMPTS):
        taken = claimed_trials(storage, app_name, sweep_verstr)
        # Never retry an index already lost: listings may lag a winner's claim.
        n = max(max(taken, default=-1) + 1, n)
        if limit is not None and n >= limit:
            return None
        claim = _claim(storage, app_name, sweep_verstr, n, 0, suggest(spec, n, past), agent)
        if claim is not None:
            return claim
        n += 1
    raise RuntimeError(f"Could not claim a trial of sweep {sweep_verstr}")


def claim_retry(storage, app_name, sweep_verstr, trial, agent=None, attempt=None):
    """Claim a new attempt at *trial*, with the original params.

    With *attempt*, claim exactly that one — None when another agent already
    did, which is how an agent that saw attempt K-1 fail avoids a duplicate
    retry. Without, claim the next free attempt. None when the trial was never
    claimed.
    """
    original = storage.load_metadata(claims_app(app_name, sweep_verstr), _record(trial, 0))
    if original is None:
        return None
    if attempt is not None:
        return _claim(storage, app_name, sweep_verstr, trial, attempt,
                      original["params"], agent)
    for _ in range(_MAX_ATTEMPTS):
        attempts = [a for t, a in _slots(storage, app_name, sweep_verstr) if t == trial]
        claim = _claim(storage, app_name, sweep_verstr, trial, max(attempts) + 1,
                       original["params"], agent)
        if claim is not None:
            return claim
    raise RuntimeError(f"Could not claim a retry of trial {trial} of {sweep_verstr}")


def attach_run(storage, claim, run_verstr):
    """Record which run carries out *claim*."""
    app = claims_app(claim["app"], claim["sweep"])
    storage.update_metadata(app, claim["verstr"], {"run": run_verstr})


def claimed_trials(storage, app_name, sweep_verstr):
    """``{trial}`` of every claimed index, in-flight claims included — one
    listing, no claim read."""
    return {trial for trial, _attempt in _slots(storage, app_name, sweep_verstr)}


def list_claims(storage, app_name, sweep_verstr):
    """Every complete claim of the sweep, ordered by (trial, attempt)."""
    app = claims_app(app_name, sweep_verstr)
    names = [_record(t, a) for t, a in sorted(_slots(storage, app_name, sweep_verstr))]
    metas = parallel_map(lambda name: storage.load_metadata(app, name), names)
    return [meta for meta in metas if meta is not None]


def _claim(storage, app_name, sweep_verstr, trial, attempt, params, agent):
    name = _record(trial, attempt)
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
    app = claims_app(app_name, sweep_verstr)
    return metadata if claim_record(storage, app, name, metadata) else None


def _record(trial, attempt):
    return f"t{trial}.a{attempt}" if attempt else f"t{trial}"


def _slots(storage, app_name, sweep_verstr):
    """``{(trial, attempt)}`` of every slot, in-flight claims included."""
    names = storage.list_record_names(claims_app(app_name, sweep_verstr))
    matches = (_SLOT.match(name) for name in names)
    return {(int(m.group(1)), int(m.group(2) or 0)) for m in matches if m}
