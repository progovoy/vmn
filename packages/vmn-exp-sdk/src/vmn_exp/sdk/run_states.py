"""Many runs' states in one call, read straight from the store.

Behind :func:`vmn_exp.sdk.reader.get_run_states`: each run costs its
``run_state.yml`` and that file's store write time (plus one existence check
when it has no state), read concurrently. Full verstrs never touch the
experiment index or list the app's runs; only ``latest`` / ``@N`` refs resolve
through it, once per call.
"""

from vmn_exp.core.refs import point_placement, resolve_experiment
from vmn_exp.core.resolve_ref import LATEST_WORDS
from vmn_exp.core.status import load_run_state, run_state_observed_at, status_fields
from vmn_exp.storage.s3_base import parallel_map


def read_run_states(storage, app_name, refs):
    """``{ref: entry or None}`` for *refs* of *app_name* in *storage*."""
    verstrs = _resolve_refs(storage, app_name, refs)
    wanted = sorted({v for v in verstrs.values() if v})
    entries = dict(zip(wanted, parallel_map(
        lambda v: run_state_entry(storage, app_name, v), wanted)))
    return {ref: entries.get(verstr) for ref, verstr in verstrs.items()}


def run_state_entry(storage, app_name, verstr):
    """Run *verstr*'s ``run_state.yml`` fields, its derived status fields, the
    raw ``run_state`` (None before the run started), its store write time
    ``observed_at`` and ``verstr`` — or None when there is no such run."""
    state = load_run_state(storage, app_name, verstr)
    if state is None and not storage.exists(app_name, verstr):
        return None
    observed = run_state_observed_at(storage, app_name, verstr) if state else None
    return dict(state or {}, **status_fields(state, observed_at=observed),
                run_state=state, observed_at=observed, verstr=verstr)


def _resolve_refs(storage, app_name, refs):
    """``{ref: verstr or None}``: a full name as given (its read tells whether
    it exists); a relative ref through one placement shared by the call."""
    placement = None
    resolved = {}
    for ref in refs:
        if ref in resolved:
            continue
        if not ref or not _is_relative(ref):
            resolved[ref] = ref or None
            continue
        placement = placement or point_placement(storage, app_name)
        verstr, err = resolve_experiment(storage, app_name, ref, snapshot=placement)
        resolved[ref] = None if err else verstr
    return resolved


def _is_relative(ref):
    return ref in LATEST_WORDS or ref.startswith("@")
