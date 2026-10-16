#!/usr/bin/env python3
"""Similar runs (plan 18), answered from the apps' index snapshots:

- ``GET .../apps/{app}/experiments/{verstr}/similar?top=10&all_apps=0`` — the
  runs most like that run, in its app or (``all_apps``) every app of its
  workspace; the run itself, its tree and its reruns (same code, params and
  inputs; forks are kept) are left out;
- ``GET .../apps/{app}/similar?text=&top=&all_apps=`` — the runs whose text
  (intent and keywords, name, note, tags, commit subjects, hypothesis)
  matches a free text, like ``vmn-exp similar --context ... --text-only``;
- ``GET /api/v1/similar?text=&top=`` — that text over every app of every
  workspace the caller may view, next to ``/api/v1/search``.

Ranking is :mod:`vmn_exp.core.similar`'s (FTS5 bm25); a run's similar runs
are ranked under its app's conf ``experiment.similar.weights``, as ``vmn-exp
similar`` ranks them (a text query matches its text alone). Never the
Postgres search rows: they carry no features or intent. Archived runs only
with ``archived=1``; ``q`` keeps the runs a query matches (the ``list
--query`` language over status-annotated rows, like ``vmn-exp similar
--query``).

Each app is searched in its FTS tables (*scope_of*, the server's
:class:`~vmn_exp.ui.similar_corpora.SimilarCorpora`): the app's index file,
or a host-local database kept in step with its snapshots. A request answers
within :data:`SEARCH_DEADLINE_SEC`, else 503 with ``Retry-After`` while the
documents are still being filed.

Answer: ``{"items": [...], "truncated"}``, each item ``{workspace, app,
verstr, name, score, reasons, signals, group_size, goal, author, timestamp,
status, note, intent}`` — ``intent`` the first 2 KB of its text and its
keywords (:func:`vmn_exp.core.similar_search.intent_excerpt`, the CLI's), or None.
"""
import time

from fastapi import HTTPException, Request
from vmn_exp.core.query import QueryError
from vmn_exp.core.similar import SimilarDeadlineExceeded, target_from_snapshot
from vmn_exp.core.similar_fts import Fts5Missing
from vmn_exp.core.similar_search import search, text_target
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.routes_search import viewable

DEFAULT_TOP = 10
MAX_TOP = 100
MAX_TEXT_BYTES = 4096
# What a request may spend on filing documents and searching before a 503.
SEARCH_DEADLINE_SEC = 10.0
RETRY_AFTER_SEC = 5


def _intent(excerpt):
    """``{"text", "keywords", "truncated"}`` of the CLI's intent *excerpt*
    (its first 2 KB, its string keywords), every key always there — or None."""
    if excerpt is None:
        return None
    return {"text": excerpt["text"], "keywords": excerpt.get("keywords", []),
            "truncated": excerpt.get("truncated", False)}


def _item(payload):
    """The CLI's item (without features) keyed by workspace and app."""
    workspace, app = payload.pop("app")
    return {"workspace": workspace, "app": app, **payload,
            "intent": _intent(payload["intent"])}


def _answer(request, scope_of, scopes, target, top, archived, query=None, weights=None):
    """The *top* items most like *target* over *scopes* — ``(workspace, app,
    snapshot, conf schema)`` — keyed by ``(workspace, app)``, so apps of one
    name in two workspaces stay apart; *weights* are the conf's overrides."""
    deadline = time.monotonic() + SEARCH_DEADLINE_SEC
    try:
        built = [scope_of((ws, app), app, snap, schema, deadline)
                 for ws, app, snap, schema in scopes]
        found = search(None, None, built, target, top=top + 1, query=query, weights=weights,
                       include_archived=archived, deadline=deadline, with_features=False)
    except QueryError as e:
        raise HTTPException(400, str(e)) from None
    except SimilarDeadlineExceeded:
        raise HTTPException(
            503, f"Similar runs took over {SEARCH_DEADLINE_SEC:g}s (the runs may still be "
                 "being indexed); retry shortly",
            headers={"Retry-After": str(RETRY_AFTER_SEC)}) from None
    except Fts5Missing as e:
        raise HTTPException(501, str(e)) from None
    items = [_item(f) for f in found[:top]]
    return json_response({"items": items, "truncated": len(found) > top}, request=request)


def _checked_top(top):
    if not 1 <= top <= MAX_TOP:
        raise HTTPException(400, f"top must be 1..{MAX_TOP}")


def _checked_text(text):
    if not text.strip():
        raise HTTPException(400, "text is required")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(400, f"text is over {MAX_TEXT_BYTES} bytes")


def register(app, prefix, app_inputs, scopes_of, segment, weights_of, scope_of):
    """Add the routes; *app_inputs(ws_name, app_tag)* → ``(app_name,
    snapshot, conf schema)``, *scopes_of(ws_names)* yields ``(ws_name,
    app_name, snapshot, conf schema)`` of every app of those workspaces,
    *segment(verstr)* returns a URL verstr or raises a 400,
    *weights_of(ws_name, app_name)* the app's conf weight overrides or None,
    *scope_of(key, app_name, snapshot, schema, deadline)* the app's search
    :class:`~vmn_exp.core.similar_corpus.Scope`
    (:meth:`~vmn_exp.ui.similar_corpora.SimilarCorpora.scope`)."""

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
        return _answer(request, scope_of, scopes(ws_name, app_name, snapshot, schema, all_apps),
                       target, top, archived, q, weights_of(ws_name, app_name))

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/similar",
             dependencies=[require(VIEWER)])
    def app_similar_text(request: Request, ws_name: str, app_tag: str, text: str = "",
                         top: int = DEFAULT_TOP, all_apps: bool = False, archived: bool = False,
                         q: str = None):
        _checked_top(top)
        _checked_text(text)
        app_name, snapshot, schema = app_inputs(ws_name, app_tag)
        return _answer(request, scope_of, scopes(ws_name, app_name, snapshot, schema, all_apps),
                       text_target(text), top, archived, q)

    @app.get(f"{prefix}/similar", dependencies=[require(VIEWER)])
    def similar_text(request: Request, text: str = "", top: int = DEFAULT_TOP,
                     archived: bool = False, q: str = None):
        _checked_top(top)
        _checked_text(text)
        names = sorted(viewable(request, [ws.name for ws in app.state.manager.list()]))
        return _answer(request, scope_of, list(scopes_of(names)), text_target(text), top,
                       archived, q)
