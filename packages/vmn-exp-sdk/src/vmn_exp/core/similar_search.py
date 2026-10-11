#!/usr/bin/env python3
"""Similar runs over a store: what ``vmn-exp similar``, the submission hint and
the SDK reader (``similar_runs``, ``run.similar()``) share.

:func:`search` scores an app's indexed runs — with *all_apps* every app's of
the store, each under its own metrics schema — against a target
(:mod:`vmn_exp.core.similar`) and shapes each result as one JSON item::

    {"app", "verstr", "name", "score", "reasons", "signals", "group_size",
     "author", "timestamp", "status", "goal": {"metric", "goal", "value"} | None,
     "note", "intent": {"text", "keywords"?, "generator"?, "truncated"?} | None,
     "features"}

``intent.text`` is the run's intent cut to :data:`INTENT_EXCERPT_BYTES`;
``note`` the record's note, else its create entry's. Every string of an
item is UTF-8 (:func:`utf8_safe`), whatever a hand-written log holds. A
query (the ``list --query`` language, over status-annotated rows) and the
archived flag narrow the candidates, never the target. The conf's ``experiment.similar`` section
holds ``weights`` (merged over the default weights; invalid values are
ignored) and ``hint`` (``false`` turns the submission hint off).
"""
import copy
from collections.abc import Mapping

from vmn_exp.core.index import direct_snapshot, indexed_snapshot
from vmn_exp.core.query import filter_rows
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.core.similar import similar_runs_multi, target_from_snapshot
from vmn_exp.core.similar_index import side_tables
from vmn_exp.core.status import derive_status
from vmn_exp.core.tree import annotate_rows
from vmn_exp.storage.areas import app_key

DEFAULT_TOP = 10
INTENT_EXCERPT_BYTES = 2048


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def similar_conf(exp_conf):
    """The ``similar`` section of an app's ``experiment`` conf, ``{}`` unless a mapping."""
    return _mapping(_mapping(exp_conf).get("similar"))


def conf_weights(exp_conf):
    """The conf's weight overrides, as given (the scorer ignores invalid ones)."""
    return similar_conf(exp_conf).get("weights")


def hint_enabled(exp_conf):
    return similar_conf(exp_conf).get("hint") is not False


def conf_schema(exp_conf):
    """The conf's ``metrics`` schema, ``{}`` unless a mapping."""
    return _mapping(_mapping(exp_conf).get("metrics"))


def app_snapshot(storage, app_name, schema=None, fallback=direct_snapshot):
    """An up-to-date index snapshot of *app_name* under the metrics *schema*."""
    return indexed_snapshot(storage, app_name, wait=True, fallback=fallback, schema=schema)


def run_target(snapshot, storage, app_name, ref, latest=False, context=None, text_only=False):
    """The target of run *ref* (or the latest); *context* replaces its text.
    ValueError when nothing matches."""
    verstr, err = resolve_experiment(storage, app_name, ref, latest=latest, snapshot=snapshot)
    if err:
        raise ValueError(err)
    try:
        return target_from_snapshot(snapshot, verstr, text=context, text_only=text_only,
                                    app=app_name)
    except KeyError:
        raise ValueError(f"Experiment '{verstr}' not found for {app_name}") from None


def text_target(context):
    """A pure text query: no run, no code facts."""
    return {"row": None, "text": context, "text_only": True}


def search(storage, app_name, snapshot, target, *, schema=None, top=DEFAULT_TOP, query=None,
           all_apps=False, schema_of=None, weights=None, include_archived=False, deadline=None):
    """The *top* runs most like *target*: :func:`item_payload` items, best first.

    *snapshot* is *app_name*'s (:func:`app_snapshot` under *schema*); with
    *all_apps* every other app of *storage* joins under ``schema_of(app)``.
    Raises ``QueryError`` on a bad *query*, ``SimilarDeadlineExceeded`` when
    the scoring runs past a *deadline* (:func:`~vmn_exp.core.similar.similar_runs_multi`).
    """
    scopes = [(app_name, snapshot, schema or {})]
    if all_apps:
        scopes += _other_scopes(storage, app_name, schema_of)
    keep = _candidate_filter(scopes, query, include_archived)
    items = similar_runs_multi(scopes, target, top=top, rows_filter=keep, weights=weights,
                               deadline=deadline)
    snapshots = {app: snap for app, snap, _ in scopes}
    return [item_payload(item, snapshots[item["app"]]) for item in items]


def _other_scopes(storage, app_name, schema_of):
    scopes = []
    for app in storage.list_apps():
        if app_key(app) != app_key(app_name):
            schema = (schema_of(app) if schema_of else None) or {}
            scopes.append((app, app_snapshot(storage, app, schema), schema))
    return scopes


def _candidate_filter(scopes, query, include_archived):
    """A ``rows_filter`` keeping archived rows only with *include_archived*
    and, with a *query*, the snapshot rows it matches — over status- and
    tree-annotated rows, like ``list --query``; None when it keeps everything.
    Matches are told apart by row identity: two apps may hold the same verstr."""
    matched = None
    if query and query.strip():
        matched = set()
        for _, snap, _ in scopes:
            rows = {row["verstr"]: row for row in snap.rows}
            matched.update(id(rows[r["verstr"]]) for r in _matching(snap, rows.values(), query))
    elif include_archived:
        return None

    def keep(row):
        return ((include_archived or not row.get("archived"))
                and (matched is None or id(row) in matched))
    return keep


def _matching(snap, rows, query):
    annotated = annotate_rows(list(rows), getattr(snap, "run_states", None),
                              getattr(snap, "run_state_observed_at", None))
    outputs_of = getattr(snap, "outputs_of", None)
    return filter_rows(annotated, query, extra={"outputs": outputs_of} if outputs_of else None)


def utf8_safe(value):
    """*value* with ``?`` for each lone surrogate of its strings (dict keys
    too): no UTF-8 encoder, JSON or stdout, fails on it. Dicts and lists are
    copied; tuples become lists."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return value.encode("utf-8", "replace").decode("utf-8")
        return value
    if isinstance(value, dict):
        return {utf8_safe(k): utf8_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [utf8_safe(v) for v in value]
    return copy.deepcopy(value)


def item_payload(item, snapshot):
    """A :func:`~vmn_exp.core.similar.similar_runs_multi` item as the JSON
    item the CLI prints (see the module docstring); copies only."""
    verstr, row = item["verstr"], item["row"]
    features_of, intent_of, _ = side_tables(snapshot)
    states = getattr(snapshot, "run_states", None) or {}
    observed = getattr(snapshot, "run_state_observed_at", None) or {}
    notes = getattr(snapshot, "create_notes", None) or {}
    return utf8_safe({
        "app": item["app"],
        "verstr": verstr,
        "name": row.get("name"),
        "score": item["score"],
        "reasons": item["reasons"],
        "signals": item["signals"],
        "group_size": item["group_size"],
        "author": row.get("author"),
        "timestamp": row.get("timestamp"),
        "status": derive_status(states.get(verstr), observed_at=observed.get(verstr)),
        "goal": item.get("goal"),
        "note": row.get("note") or notes.get(verstr),
        "intent": intent_excerpt(intent_of(verstr)),
        "features": features_of(verstr),
    })


def intent_excerpt(intent):
    """*intent*'s text cut to :data:`INTENT_EXCERPT_BYTES` of UTF-8 (on a
    character boundary; ``truncated`` when cut, or cut when written), with
    its string ``keywords`` and its ``generator``; None without one. A lone
    surrogate (only a hand-written log holds one) is no UTF-8: it reads ``?``."""
    if not intent:
        return None
    found = {"keywords": _string_keywords(intent.get("keywords")),
             "generator": utf8_safe(intent.get("generator"))}
    excerpt = {key: value for key, value in found.items() if value}
    raw = str(intent.get("text") or "").encode("utf-8", "replace")
    excerpt["text"] = raw[:INTENT_EXCERPT_BYTES].decode("utf-8", "ignore")
    if len(raw) > INTENT_EXCERPT_BYTES or intent.get("truncated"):
        excerpt["truncated"] = True
    return excerpt


def _string_keywords(keywords):
    """The strings of a folded intent's *keywords*: the fold checks only its
    text, and readers (the web UI) take each keyword for a string."""
    if not isinstance(keywords, (list, tuple)):
        return []
    return [utf8_safe(k) for k in keywords if isinstance(k, str)]


def find(storage, app_name, ref="latest", exp_conf=None, *, top=DEFAULT_TOP, query=None,
         context=None, text_only=False, all_apps=False, schema_of=None):
    """:func:`search` for run *ref* of *app_name* (the latest when None),
    or — *ref* None with *text_only* — for the *context* text alone, under
    the app's ``experiment`` conf *exp_conf* (schema, weights). ValueError
    for an unknown ref or *text_only* without a *context*."""
    if text_only and not (context or "").strip():
        raise ValueError("A text-only search needs a context text")
    schema = conf_schema(exp_conf)
    snapshot = app_snapshot(storage, app_name, schema)
    if ref is None and text_only:
        target = text_target(context)
    else:
        target = run_target(snapshot, storage, app_name, ref or "latest", context=context,
                            text_only=text_only)
    return search(storage, app_name, snapshot, target, schema=schema, top=top, query=query,
                  all_apps=all_apps, schema_of=schema_of, weights=conf_weights(exp_conf))
