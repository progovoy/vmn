#!/usr/bin/env python3
"""``GET .../apps/{app}/experiments/{verstr}/sweep``: the sweep's spec, status
summary and trials, their target metric attributed as ``vmn-exp sweep status``
does (a trial's own, else its nested runs'). Rows come from the app's index
snapshot — the sweep's subtree only; the spec from the sweep run's metadata.
The first :data:`MAX_TRIALS` trials are served (``trials_total`` counts
them all; the rest are the job's Runs tab), and ``job`` is the job's compact
rollup (plan 23 S3)."""
from fastapi import HTTPException, Request
from vmn_exp.core.sweep.claims import claimed_trials
from vmn_exp.core.sweep.spec import SpecError, parse_spec
from vmn_exp.core.sweep.summary import snapshot_trials
from vmn_exp.core.sweep.view import sweep_view
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.responses import json_response

MAX_TRIALS = 50


def _spec_of(storage, app_name, verstr):
    meta = storage.load_metadata(app_name, verstr) or {}
    try:
        return parse_spec(meta["sweep"]) if meta.get("sweep") else None
    except SpecError:
        return None


def register(app, prefix, sweep_inputs, segment, job_of):
    """Add the route; *sweep_inputs(ws_name, app_tag)* →
    ``(app_name, snapshot_for(app_name), storage)``, *segment(verstr)* returns
    a URL verstr or raises a 400, *job_of(ws_name, app_tag, verstr)* the
    job's compact rollup (None without trials)."""

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}/sweep", dependencies=[require(VIEWER)])
    def experiment_sweep(request: Request, ws_name: str, app_tag: str, verstr: str):
        segment(verstr)
        app_name, snapshot_for, storage = sweep_inputs(ws_name, app_tag)
        spec = _spec_of(storage, app_name, verstr)
        if spec is None:
            raise HTTPException(404, f"{verstr} is not a sweep of {app_name}")
        trials = snapshot_trials(spec, verstr, snapshot_for(app_name))
        payload = sweep_view(spec, verstr, trials, claimed_trials(storage, app_name, verstr))
        payload["trials_total"] = len(payload["trials"])
        payload["trials"] = payload["trials"][:MAX_TRIALS]
        payload["job"] = job_of(ws_name, app_tag, verstr)
        return json_response(payload, request=request)
