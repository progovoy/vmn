#!/usr/bin/env python3
"""Similar runs (plan 18), answered from the apps' index snapshots:

- ``GET .../apps/{app}/experiments/{verstr}/similar?top=10&all_apps=0`` — the
  runs most like that run, in its app or (``all_apps``) every app of its
  workspace; the run itself, the runs of its exact code and its tree are left out;
- ``GET .../apps/{app}/similar?text=&top=&all_apps=`` — the runs whose text
  (intent and keywords, name, note, tags, commit subjects, hypothesis)
  matches a free text, like ``vmn-exp similar --context ... --text-only``;
- ``GET /api/v1/similar?text=&top=`` — that text over every app of every
  workspace the caller may view, next to ``/api/v1/search``.

Scoring is :mod:`vmn_exp.core.similar`'s; a run's similar runs are scored
under its app's conf ``experiment.similar.weights``, as ``vmn-exp similar``
scores them (a text query scores its text alone). Its inverted
index is built once per snapshot object, and an app's snapshot is the same
object until its index moves to a new generation, so requests against an
unchanged app reuse it. Never the Postgres search rows: they carry no
features or intent. Archived runs only with ``archived=1``.

Answer: ``{"items": [...], "truncated"}``, each item ``{workspace, app,
verstr, name, score, reasons, signals, group_size, goal, author, timestamp,
status, note, intent}`` — ``intent`` the first 2 KB of its text and its
keywords (:func:`vmn_exp.core.similar_search.intent_excerpt`, the CLI's), or None.
"""
from fastapi import HTTPException, Request
from vmn_exp.core.similar import similar_runs_multi, target_from_snapshot
from vmn_exp.core.similar_search import intent_excerpt as _excerpt
from vmn_exp.core.status import derive_status
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.routes_search import viewable

DEFAULT_TOP = 10
MAX_TOP = 100
MAX_TEXT_BYTES = 4096


def intent_excerpt(intent):
    """``{"text", "keywords", "truncated"}`` of an intent — the CLI's excerpt
    (its first 2 KB, its string keywords), every key always there — or None."""
    excerpt = _excerpt(intent)
    if excerpt is None:
        return None
    return {"text": excerpt["text"], "keywords": excerpt.get("keywords", []),
            "truncated": excerpt.get("truncated", False)}


def _item(found, snapshot):
    (workspace, app), verstr, row = found["app"], found["verstr"], found["row"]
    status = derive_status(snapshot.run_states.get(verstr),
                           observed_at=snapshot.run_state_observed_at.get(verstr))
    return {
        "workspace": workspace, "app": app, "verstr": verstr, "name": row.get("name"),
        "score": found["score"], "reasons": found["reasons"], "signals": found["signals"],
        "group_size": found["group_size"], "goal": found["goal"],
        "author": row.get("author"), "timestamp": row.get("timestamp"), "status": status,
        "note": row.get("note"), "intent": intent_excerpt(snapshot.intent_of(verstr)),
    }


def _unarchived(row):
    return not row.get("archived")


def _answer(request, scopes, target, top, archived, weights=None):
    """The *top* items most like *target* over *scopes* — ``(workspace, app,
    snapshot, conf schema)`` — keyed by ``(workspace, app)``, so apps of one
    name in two workspaces stay apart; *weights* are the conf's overrides."""
    snapshots = {(ws, app): snap for ws, app, snap, _ in scopes}
    found = similar_runs_multi(
        [((ws, app), snap, schema) for ws, app, snap, schema in scopes], target,
        top=top + 1, rows_filter=None if archived else _unarchived, weights=weights,
    )
    items = [_item(f, snapshots[f["app"]]) for f in found[:top]]
    return json_response({"items": items, "truncated": len(found) > top}, request=request)


def _checked_top(top):
    if not 1 <= top <= MAX_TOP:
        raise HTTPException(400, f"top must be 1..{MAX_TOP}")


def _checked_text(text):
    if not text.strip():
        raise HTTPException(400, "text is required")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(400, f"text is over {MAX_TEXT_BYTES} bytes")


def _text_target(text):
    return {"row": None, "features": None, "intent": None, "hypothesis": None,
            "text": text, "text_only": True}


def register(app, prefix, app_inputs, scopes_of, segment, weights_of):
    """Add the routes; *app_inputs(ws_name, app_tag)* → ``(app_name,
    snapshot, conf schema)``, *scopes_of(ws_names)* yields ``(ws_name,
    app_name, snapshot, conf schema)`` of every app of those workspaces,
    *segment(verstr)* returns a URL verstr or raises a 400,
    *weights_of(ws_name, app_name)* the app's conf weight overrides or None."""

    def scopes(ws_name, app_name, snapshot, schema, all_apps):
        return list(scopes_of([ws_name])) if all_apps else [(ws_name, app_name, snapshot, schema)]

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}/similar",
             dependencies=[require(VIEWER)])
    def experiment_similar(request: Request, ws_name: str, app_tag: str, verstr: str,
                           top: int = DEFAULT_TOP, all_apps: bool = False, archived: bool = False):
        segment(verstr)
        _checked_top(top)
        app_name, snapshot, schema = app_inputs(ws_name, app_tag)
        if snapshot.row(verstr) is None:
            raise HTTPException(404, f"{verstr} is not a run of {app_name}")
        target = target_from_snapshot(snapshot, verstr, app=(ws_name, app_name))
        return _answer(request, scopes(ws_name, app_name, snapshot, schema, all_apps),
                       target, top, archived, weights_of(ws_name, app_name))

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/similar",
             dependencies=[require(VIEWER)])
    def app_similar_text(request: Request, ws_name: str, app_tag: str, text: str = "",
                         top: int = DEFAULT_TOP, all_apps: bool = False, archived: bool = False):
        _checked_top(top)
        _checked_text(text)
        app_name, snapshot, schema = app_inputs(ws_name, app_tag)
        return _answer(request, scopes(ws_name, app_name, snapshot, schema, all_apps),
                       _text_target(text), top, archived)

    @app.get(f"{prefix}/similar", dependencies=[require(VIEWER)])
    def similar_text(request: Request, text: str = "", top: int = DEFAULT_TOP,
                     archived: bool = False):
        _checked_top(top)
        _checked_text(text)
        names = sorted(viewable(request, [ws.name for ws in app.state.manager.list()]))
        return _answer(request, list(scopes_of(names)), _text_target(text), top, archived)
