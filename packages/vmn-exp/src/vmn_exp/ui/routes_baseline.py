#!/usr/bin/env python3
"""An outer run against its baseline (plan 28 N3):
``GET .../experiments/{verstr}/baseline?to=&match=&by=`` (the rollup deltas,
attention shares, own metrics, paired children and chip) and
``GET .../experiments-baselines?v=...`` (the chips of many outer runs, what
a Jobs view page shows: one request per page, computed for its rows only).
``match`` (comma-separated ``params.<k>``/``tags.<k>``) and ``by`` (one
field, empty: no pairing) override the app's ``experiment.ui.baseline``;
``to`` overrides the choice. See :mod:`~vmn_exp.ui.baseline_views`. A run
without children is a 404; the comparison is memoized, its encoded body kept
per ETag.
"""
from typing import List

from fastapi import HTTPException, Query, Request
from vmn_exp.core.app_settings import SettingsError, baseline_fields, check_field
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.baseline_views import UnknownBaseline
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.responses import memoized_json_response

ENCODED_BODIES = 64
MAX_CHIPS = 200


def _rule_args(match, by):
    """The request's ``(match fields, by)``, None where it names none; 400 on a bad field."""
    try:
        fields = None if match is None else baseline_fields(match)
        if by:
            check_field(by, "by")
    except SettingsError as exc:
        raise HTTPException(400, str(exc)) from exc
    return fields, by


def register(app, prefix, leaderboard_inputs, baselines, segment, attention_of):
    """*leaderboard_inputs(ws_name, app_tag)* -> ``(snapshot, effective
    schema)``; *baselines* a :class:`~vmn_exp.ui.baseline_views.BaselineViews`;
    *segment(verstr)* raises a 400 for an unsafe verstr;
    *attention_of(ws_name, app_tag)* the app's attention entries."""
    base = f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"
    bodies = LRU(ENCODED_BODIES)

    @app.get(f"{base}/experiments/{{verstr}}/baseline", dependencies=[require(VIEWER)])
    def experiment_baseline(request: Request, ws_name: str, app_tag: str, verstr: str,
                            to: str = None, match: str = None, by: str = None):
        segment(verstr)
        if to:
            segment(to)
        fields, by = _rule_args(match, by)
        snapshot, schema = leaderboard_inputs(ws_name, app_tag)
        if not baselines.views.is_job(snapshot, verstr):
            raise HTTPException(404, f"{verstr} is not an outer run (it has no runs under it)")
        args = dict(to=to or None, match=fields, by=by, attention=attention_of(ws_name, app_tag))
        try:
            body, etag = baselines.answer(snapshot, schema, verstr, **args)
        except UnknownBaseline as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return memoized_json_response(request, etag, lambda: body, bodies)

    @app.get(f"{base}/experiments-baselines", dependencies=[require(VIEWER)])
    def experiment_baselines(request: Request, ws_name: str, app_tag: str,
                             v: List[str] = Query(default=[]), match: str = None,
                             by: str = None):
        if len(v) > MAX_CHIPS:
            raise HTTPException(400, f"at most {MAX_CHIPS} runs a request")
        for verstr in v:
            segment(verstr)
        fields, by = _rule_args(match, by)
        snapshot, schema = leaderboard_inputs(ws_name, app_tag)
        etag = baselines.chips_etag(snapshot, schema, v, match=fields, by=by)
        return memoized_json_response(request, etag, lambda: {
            "chips": baselines.chips(snapshot, schema, v, match=fields, by=by)}, bodies)
