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
scores them (a text query scores its text alone). Never the Postgres
search rows: they carry no features or intent. Archived runs only with
``archived=1``; ``q`` keeps the runs a query matches (the ``list --query``
language over status-annotated rows, like ``vmn-exp similar --query``).

An app's inverted index is built once per snapshot object (the same object
until the app's index moves to a new generation), off the request thread —
every app's of a request at once — and from its previous generation's
(:class:`~vmn_exp.core.similar_cache.IndexLineages`): a heartbeat reuses
it, other changes cost what changed, concurrent requests share one build,
and a text query files words only. A request answers within
:data:`SEARCH_DEADLINE_SEC`, else 503 with ``Retry-After`` while the build
goes on.

Answer: ``{"items": [...], "truncated"}``, each item ``{workspace, app,
verstr, name, score, reasons, signals, group_size, goal, author, timestamp,
status, note, intent}`` — ``intent`` the first 2 KB of its text and its
keywords (:func:`vmn_exp.core.similar_search.intent_excerpt`, the CLI's), or None.
"""
import time

from fastapi import HTTPException, Request
from vmn_exp.core.query import QueryError
from vmn_exp.core.similar import (
    SimilarDeadlineExceeded,
    similar_runs_multi,
    target_from_snapshot,
)
from vmn_exp.core.similar_cache import IndexLineages
from vmn_exp.core.similar_search import candidate_filter, text_target
from vmn_exp.core.similar_search import intent_excerpt as _excerpt
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.routes_search import viewable

DEFAULT_TOP = 10
MAX_TOP = 100
MAX_TEXT_BYTES = 4096
# What a request may spend on building indexes and scoring before a 503.
SEARCH_DEADLINE_SEC = 10.0
RETRY_AFTER_SEC = 5


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
    return {
        "workspace": workspace, "app": app, "verstr": verstr, "name": row.get("name"),
        "score": found["score"], "reasons": found["reasons"], "signals": found["signals"],
        "group_size": found["group_size"], "goal": found["goal"],
        "author": row.get("author"), "timestamp": row.get("timestamp"),
        "status": snapshot.status_of(verstr),
        "note": row.get("note"), "intent": intent_excerpt(snapshot.intent_of(verstr)),
    }


def _answer(request, lineages, scopes, target, top, archived, query=None, weights=None):
    """The *top* items most like *target* over *scopes* — ``(workspace, app,
    snapshot, conf schema)`` — keyed by ``(workspace, app)``, so apps of one
    name in two workspaces stay apart; *weights* are the conf's overrides."""
    deadline = time.monotonic() + SEARCH_DEADLINE_SEC
    keyed = [((ws, app), snap, schema) for ws, app, snap, schema in scopes]
    try:
        keep = candidate_filter(keyed, query, archived)
    except QueryError as e:
        raise HTTPException(400, str(e)) from None
    structured = not target.get("text_only")
    for key, snap, _ in keyed:
        lineages.start(key, snap, structured)
    try:
        for key, snap, _ in keyed:
            lineages.index_for(key, snap, deadline, structured)
        found = similar_runs_multi(keyed, target, top=top + 1, rows_filter=keep,
                                   weights=weights, deadline=deadline)
    except SimilarDeadlineExceeded:
        raise HTTPException(
            503, f"Similar runs took over {SEARCH_DEADLINE_SEC:g}s (the runs may still be "
                 "being indexed); retry shortly",
            headers={"Retry-After": str(RETRY_AFTER_SEC)}) from None
    snapshots = {key: snap for key, snap, _ in keyed}
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


def register(app, prefix, app_inputs, scopes_of, segment, weights_of):
    """Add the routes; *app_inputs(ws_name, app_tag)* → ``(app_name,
    snapshot, conf schema)``, *scopes_of(ws_names)* yields ``(ws_name,
    app_name, snapshot, conf schema)`` of every app of those workspaces,
    *segment(verstr)* returns a URL verstr or raises a 400,
    *weights_of(ws_name, app_name)* the app's conf weight overrides or None."""

    lineages = IndexLineages()

    def scopes(ws_name, app_name, snapshot, schema, all_apps):
        return list(scopes_of([ws_name])) if all_apps else [(ws_name, app_name, snapshot, schema)]

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}/similar",
             dependencies=[require(VIEWER)])
    def experiment_similar(request: Request, ws_name: str, app_tag: str, verstr: str,
                           top: int = DEFAULT_TOP, all_apps: bool = False, archived: bool = False,
                           q: str = None):
        segment(verstr)
        _checked_top(top)
        app_name, snapshot, schema = app_inputs(ws_name, app_tag)
        if snapshot.row(verstr) is None:
            raise HTTPException(404, f"{verstr} is not a run of {app_name}")
        target = target_from_snapshot(snapshot, verstr, app=(ws_name, app_name))
        return _answer(request, lineages, scopes(ws_name, app_name, snapshot, schema, all_apps),
                       target, top, archived, q, weights_of(ws_name, app_name))

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/similar",
             dependencies=[require(VIEWER)])
    def app_similar_text(request: Request, ws_name: str, app_tag: str, text: str = "",
                         top: int = DEFAULT_TOP, all_apps: bool = False, archived: bool = False,
                         q: str = None):
        _checked_top(top)
        _checked_text(text)
        app_name, snapshot, schema = app_inputs(ws_name, app_tag)
        return _answer(request, lineages, scopes(ws_name, app_name, snapshot, schema, all_apps),
                       text_target(text), top, archived, q)

    @app.get(f"{prefix}/similar", dependencies=[require(VIEWER)])
    def similar_text(request: Request, text: str = "", top: int = DEFAULT_TOP,
                     archived: bool = False, q: str = None):
        _checked_top(top)
        _checked_text(text)
        names = sorted(viewable(request, [ws.name for ws in app.state.manager.list()]))
        return _answer(request, lineages, list(scopes_of(names)), text_target(text), top,
                       archived, q)
