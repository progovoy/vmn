#!/usr/bin/env python3
"""``GET .../apps/{app}/experiments/{verstr}/sweep``: the sweep's spec, status
summary and trials, their target metric attributed as ``vmn-exp sweep status``
does (a trial's own, else its nested runs'). Rows come from the app's index
snapshot — the sweep's subtree only; the spec from the sweep run's metadata."""
from fastapi import HTTPException, Request

from vmn_exp.core.sweep.claims import claimed_trials
from vmn_exp.core.sweep.spec import SpecError, parse_spec
from vmn_exp.core.sweep.summary import snapshot_trials
from vmn_exp.core.sweep.view import sweep_view
from vmn_exp.ui.responses import json_response


def _spec_of(storage, app_name, verstr):
    meta = storage.load_metadata(app_name, verstr) or {}
    try:
        return parse_spec(meta["sweep"]) if meta.get("sweep") else None
    except SpecError:
        return None


def register(app, prefix, sweep_inputs, segment):
    """Add the route; *sweep_inputs(ws_name, app_tag)* →
    ``(app_name, snapshot_for(app_name), storage)``, *segment(verstr)* returns
    a URL verstr or raises a 400."""

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}/sweep")
    def experiment_sweep(request: Request, ws_name: str, app_tag: str, verstr: str):
        segment(verstr)
        app_name, snapshot_for, storage = sweep_inputs(ws_name, app_tag)
        spec = _spec_of(storage, app_name, verstr)
        if spec is None:
            raise HTTPException(404, f"{verstr} is not a sweep of {app_name}")
        trials = snapshot_trials(spec, verstr, snapshot_for(app_name))
        payload = sweep_view(spec, verstr, trials, claimed_trials(storage, app_name, verstr))
        return json_response(payload, request=request)
