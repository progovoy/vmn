#!/usr/bin/env python3
"""Similar runs over a store: what ``vmn-exp similar``, the submission hint and
the SDK reader (``similar_runs``, ``run.similar()``) share.

:func:`search` ranks an app's runs — with *all_apps* every app's of the
store, each under its own metrics schema — against a target
(:mod:`vmn_exp.core.similar`) and shapes each result as one JSON item
(:mod:`vmn_exp.core.similar_items`). A query (the ``list --query`` language,
over status-annotated rows) and the archived flag narrow the candidates,
never the target. The conf's ``experiment.similar`` section holds
``weights`` (merged over the default weights; invalid values are ignored)
and ``hint`` (``false`` turns the submission hint off).

An app is searched in its persisted index file (:func:`app_scope`): a fresh
process brings the file up to date with storage, edits in place included
(:meth:`~vmn_exp.core.index.ExperimentIndex.sync`: a journaled store's
changes since, else a names listing), and reads the few runs a query looks
at by verstr — no snapshot of the app. A query (which filters
snapshot rows), a store never indexed yet or no index file at all take the
refreshed snapshot; without a file the search runs on a ``:memory:``
database filled from it. A target run is read from its own record, so what
it just logged counts.
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.app_conf import read_experiment_conf
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import direct_snapshot, indexed_snapshot, shared_index, snapshot_of_folds
from vmn_exp.core.index_point import index_path, point_view
from vmn_exp.core.log import load_log
from vmn_exp.core.query import filter_rows
from vmn_exp.core.query_extra import snapshot_extra
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.core.similar import similar_runs_multi, target_from_snapshot
from vmn_exp.core.similar_corpus import Scope, file_scope, snapshot_scope
from vmn_exp.core.similar_items import (  # noqa: F401  (re-exported)
    INTENT_EXCERPT_BYTES,
    intent_excerpt,
    item_payload,
    utf8_safe,
)
from vmn_exp.core.similar_profile import _dict
from vmn_exp.core.similar_rows import SnapshotRows
from vmn_exp.core.status import load_run_state
from vmn_exp.core.tree import annotate_rows
from vmn_exp.storage.areas import app_key

DEFAULT_TOP = 10


def similar_conf(exp_conf):
    """The ``similar`` section of an app's ``experiment`` conf, ``{}`` unless a mapping."""
    return _dict(_dict(exp_conf).get("similar"))


def conf_weights(exp_conf):
    """The conf's weight overrides, as given (invalid ones are ignored later)."""
    return similar_conf(exp_conf).get("weights")


def hint_enabled(exp_conf):
    return similar_conf(exp_conf).get("hint") is not False


def conf_schema(exp_conf):
    """The conf's ``metrics`` schema, ``{}`` unless a mapping."""
    return _dict(_dict(exp_conf).get("metrics"))


def conf_schema_of(root):
    """``schema_of(app)`` for :func:`search`: an app's conf metrics schema,
    read from its conf.yml in the checkout at *root*."""
    return lambda app: conf_schema(read_experiment_conf(app, root))


def app_snapshot(storage, app_name, schema=None):
    """An up-to-date index snapshot of *app_name* under the metrics *schema*."""
    return indexed_snapshot(storage, app_name, wait=True, fallback=direct_snapshot, schema=schema)


def app_scope(storage, app_name, schema=None, with_snapshot=False):
    """The :class:`~vmn_exp.core.similar_corpus.Scope` *app_name* is searched
    in (see the module docstring); *with_snapshot* reads its rows from a
    refreshed snapshot (what a query filters)."""
    path = index_path(storage, app_name)
    if path and not with_snapshot and _synced(storage, app_name):
        scope = file_scope(app_name, path, schema)
        if scope is not None:
            return scope
    snapshot = app_snapshot(storage, app_name, schema)
    scope = file_scope(app_name, path, schema, snapshot) if path else None
    return scope or snapshot_scope(app_name, snapshot, schema)


def _placement(storage, app_name, scope):
    """Where to resolve a ref once :func:`app_scope` gave *scope*: its
    snapshot, else the index file it just synced (no second listing)."""
    if isinstance(scope.rows, SnapshotRows):
        return scope.rows.snapshot
    try:
        return point_view(storage, app_name, sync=False)
    except Exception:
        VMN_LOGGER.debug("Experiment index point read unavailable", exc_info=True)
        return None


def _synced(storage, app_name):
    """Whether the persisted index now holds *app_name*'s runs as they are
    (:meth:`~vmn_exp.core.index.ExperimentIndex.sync`)."""
    try:
        return shared_index(storage, app_name).sync()
    except Exception:
        VMN_LOGGER.debug("Experiment index sync failed", exc_info=True)
        return False


def record_target(storage, app_name, verstr, context=None, text_only=False, command=None):
    """The target of run *verstr*, read from its own record in *storage* (its
    run state's command unless *command* is given); KeyError when absent."""
    meta = storage.load_metadata(app_name, verstr)
    if meta is None:
        raise KeyError(verstr)
    fold = fold_log(load_log(storage, app_name, verstr))
    target = target_from_snapshot(snapshot_of_folds(app_name, [(1, meta, fold)]), verstr,
                                  text=context, text_only=text_only, app=app_name)
    state = load_run_state(storage, app_name, verstr) or {}
    target["command"] = list(command) if command else state.get("command")
    return target


def run_target(storage, app_name, ref, latest=False, context=None, text_only=False,
               placement=None):
    """The target of run *ref* (or the latest), resolved in *placement*
    (an up-to-date snapshot or point view; default: the storage's index);
    *context* replaces its text. ValueError when nothing matches."""
    verstr, err = resolve_experiment(storage, app_name, ref, latest=latest, snapshot=placement)
    if err:
        raise ValueError(err)
    try:
        return record_target(storage, app_name, verstr, context, text_only)
    except KeyError:
        raise ValueError(f"Experiment '{verstr}' not found for {app_name}") from None


def text_target(context):
    """A pure text query: no run, no code facts."""
    return {"row": None, "text": context, "text_only": True}


def search(storage, app_name, source, target, *, schema=None, top=DEFAULT_TOP, query=None,
           all_apps=False, schema_of=None, weights=None, include_archived=False, deadline=None,
           with_features=True):
    """The *top* runs most like *target*: :func:`item_payload` items, best first.

    *source* is *app_name*'s :class:`~vmn_exp.core.similar_corpus.Scope`
    (:func:`app_scope`), its snapshot under *schema*, or a list of ready
    scopes (each labelling its results); with *all_apps* every
    other app of *storage* joins under ``schema_of(app)``. Raises
    ``QueryError`` on a bad *query*, ``SimilarDeadlineExceeded`` past a
    *deadline* (:func:`~vmn_exp.core.similar.similar_runs_multi`).
    """
    if isinstance(source, list):
        scopes = list(source)
    else:
        scopes = [source if isinstance(source, Scope)
                  else snapshot_scope(app_name, source, schema or {})]
    query = _query(query)
    if all_apps:
        scopes += _other_scopes(storage, app_name, schema_of, bool(query))
    keep = candidate_filter(scopes, query, include_archived)
    items = similar_runs_multi(scopes, target, top=top, rows_filter=keep, weights=weights,
                               deadline=deadline)
    rows_of = {scope.label: scope.rows for scope in scopes}
    for label, rows in rows_of.items():
        prefetch = getattr(rows, "prefetch", None)  # facts read for all shown at once
        if prefetch is not None:
            prefetch([item["row"] for item in items if item["app"] == label])
    return [item_payload(item, rows_of[item["app"]], with_features) for item in items]


def _query(query):
    """*query* stripped, None when blank."""
    return (query or "").strip() or None


def _other_scopes(storage, app_name, schema_of, with_snapshot):
    """The other apps' scopes, in app order; their indexes are brought up to
    date side by side."""
    # Lazily: the thread pool's module stays off the SDK reader's import path.
    from vmn_exp.storage.s3_base import parallel_map

    apps = [app for app in storage.list_apps() if app_key(app) != app_key(app_name)]
    schemas = [(schema_of(app) if schema_of else None) or {} for app in apps]
    return parallel_map(lambda pair: app_scope(storage, *pair, with_snapshot=with_snapshot),
                        list(zip(apps, schemas)))


def candidate_filter(scopes, query, include_archived):
    """A ``rows_filter(label, row)`` keeping archived rows only with
    *include_archived* and, with a *query*, the rows it matches — over
    status- and tree-annotated snapshot rows, like ``list --query`` (each
    scope's rows then come from a snapshot); None when it keeps everything."""
    matched = None
    query = _query(query)
    if query:
        matched = {}
        for scope in scopes:
            snap = scope.rows.snapshot if isinstance(scope.rows, SnapshotRows) else None
            rows = snap.rows if snap is not None else ()
            matched[scope.label] = {r["verstr"] for r in _matching(scope, snap, rows, query)}
    elif include_archived:
        return None

    def keep(label, row):
        return ((include_archived or not row.get("archived"))
                and (matched is None or row["verstr"] in matched.get(label, ())))
    return keep


def _matching(scope, snap, rows, query):
    """*rows* of *snap* matching *query*, its ``similar()`` searching *scope*."""
    annotated = annotate_rows(list(rows), snap.run_states, snap.run_state_observed_at)
    return filter_rows(annotated, query, extra=snapshot_extra(snap, lambda _: scope))


def find(storage, app_name, ref="latest", exp_conf=None, *, top=DEFAULT_TOP, query=None,
         context=None, text_only=False, all_apps=False, schema_of=None, target=None,
         include_archived=False):
    """:func:`search` for run *ref* of *app_name* (the latest when None),
    or — *ref* None with *text_only* — for the *context* text alone, or for
    a ready *target* (the CLI's working tree), under the app's
    ``experiment`` conf *exp_conf* (schema, weights). ValueError for an
    unknown ref or *text_only* without a *context*."""
    if text_only and not (context or "").strip():
        raise ValueError("A text-only search needs a context text")
    schema = conf_schema(exp_conf)
    scope = app_scope(storage, app_name, schema, with_snapshot=bool(_query(query)))
    if target is None and ref is None and text_only:
        target = text_target(context)
    elif target is None:
        target = run_target(storage, app_name, ref or "latest", context=context,
                            text_only=text_only, placement=_placement(storage, app_name, scope))
    return search(storage, app_name, scope, target, schema=schema, top=top, query=query,
                  all_apps=all_apps, schema_of=schema_of, weights=conf_weights(exp_conf),
                  include_archived=include_archived)
