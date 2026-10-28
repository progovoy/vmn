#!/usr/bin/env python3
"""What a query reads of an index snapshot beyond its lean rows (plan 24 F5).

:func:`snapshot_extra` is :func:`~vmn_exp.core.query.filter_rows`' *extra*
for the rows of a snapshot: ``outputs`` (``outputs_of``), ``ancestors``
(``under()``, from its ``edges``), ``intent``/``keywords`` (the latest
intent's text and keyword list, from ``intent_of``) and ``similar``
(``similar()``, :mod:`vmn_exp.core.query_similar`). :func:`ancestor_extra`
adds the reader of ``up`` fields (other rows of the snapshot, memoized per
snapshot, :func:`~vmn_exp.core.query_up.ancestor_fields`); :func:`lean_extra`
and :func:`store_extra` carry it. Every entry point that
filters snapshot rows takes its extra from here.

``similar()`` searches, in order: the scope a caller passes, the scope bound
to the snapshot (:func:`bind_similar_scope`: ``vmn-exp ui`` binds each
snapshot it serves to its app's search scope), else a ``:memory:`` database
filled from the snapshot (:func:`~vmn_exp.core.similar_corpus.snapshot_scope`).
:func:`store_extra` passes the app's persisted index file first. Lean rows
leave a run's ``sys_*`` metrics out (row copies carry them): filtering the
snapshot's own rows takes :func:`lean_extra`, which reads them back for a
``metrics.sys_*`` field (:func:`reads_off_row`).
"""
import weakref

from vmn_exp.core.index_point import index_path
from vmn_exp.core.index_snapshot import schema_less
from vmn_exp.core.query import (
    ANCESTORS,
    SIMILAR,
    SYSTEM_METRICS,
    query_roots,
    reads_system_metrics,
)
from vmn_exp.core.query_similar import scope_matcher
from vmn_exp.core.query_up import UP, ancestor_fields
from vmn_exp.core.tree import ancestors

INTENT, KEYWORDS = "intent", "keywords"
# The query roots answered from the snapshot, not the rows.
SNAPSHOT_FIELDS = frozenset({"outputs", ANCESTORS, INTENT, KEYWORDS, SIMILAR})

_BOUND = weakref.WeakKeyDictionary()  # snapshot -> scope_of(snapshot)


def bind_similar_scope(snapshot, scope_of):
    """``similar()`` over *snapshot* (and its summarized views) searches
    ``scope_of(the snapshot asked)``; *scope_of* must not hold the snapshot."""
    _BOUND[snapshot] = scope_of


def _bound(snapshot):
    for snap in (snapshot, schema_less(snapshot)):
        found = _BOUND.get(snap) if snap is not None else None
        if found is not None:
            return found
    return None


def _memory_scope(snapshot):
    from vmn_exp.core.similar_corpus import snapshot_scope

    base = schema_less(snapshot)  # one database for its views
    return snapshot_scope(base.app_name, base)


def intent_text(intent):
    return (intent or {}).get("text")


def intent_keywords(intent):
    return (intent or {}).get("keywords")


def snapshot_extra(snapshot, scope_of=None):
    """The extra of *snapshot*'s rows (None without a snapshot);
    ``scope_of(snapshot)`` gives the scope ``similar()`` searches."""
    if snapshot is None:
        return None
    edges, intent_of = snapshot.edges, snapshot.intent_of
    scope_of = scope_of or _bound(snapshot) or _memory_scope
    return {
        "outputs": snapshot.outputs_of,
        ANCESTORS: lambda verstr: ancestors(verstr, edges),
        INTENT: lambda verstr: intent_text(intent_of(verstr)),
        KEYWORDS: lambda verstr: intent_keywords(intent_of(verstr)),
        SIMILAR: scope_matcher(lambda: scope_of(snapshot)),
    }


def ancestor_extra(snapshot):
    """``{"up": verstr -> up reader}`` over *snapshot*, its memo looked up once."""
    found = []

    def of(verstr):
        if not found:
            found.append(ancestor_fields(snapshot))
        return found[0].of(verstr)

    return {UP: of}


def lean_extra(snapshot, scope_of=None):
    """:func:`snapshot_extra` for *snapshot*'s own (lean) rows, with the
    ``sys_*`` metrics they leave out (:data:`~vmn_exp.core.query.SYSTEM_METRICS`)."""
    extra = snapshot_extra(snapshot, scope_of)
    if extra is not None:
        extra[SYSTEM_METRICS] = lambda verstr: snapshot.system_metrics_of(verstr)
        extra.update(ancestor_extra(snapshot))
    return extra


def reads_off_row(text):
    """Whether query *text* reads what a lean row lacks: a snapshot field
    (:data:`SNAPSHOT_FIELDS`), an ``up`` field or a ``sys_*`` metric."""
    roots = query_roots(text)
    return bool(SNAPSHOT_FIELDS & roots) or UP in roots or reads_system_metrics(text)


def store_extra(storage, app_name, snapshot):
    """:func:`snapshot_extra` and :func:`ancestor_extra`, ``similar()``
    searching *app_name*'s persisted index file in *storage* when it has
    one, else the snapshot's ``:memory:`` database."""

    def scope_of(snap):
        from vmn_exp.core.similar_corpus import file_scope

        path = index_path(storage, app_name)
        return (file_scope(app_name, path, snapshot=snap) if path else None) or _memory_scope(snap)

    extra = snapshot_extra(snapshot, scope_of)
    return extra and {**extra, **ancestor_extra(snapshot)}
