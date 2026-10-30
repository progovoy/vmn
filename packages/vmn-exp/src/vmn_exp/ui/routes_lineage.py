#!/usr/bin/env python3
"""``GET .../apps/{app}/experiments/{verstr}/lineage?depth=1&limit=100`` and
``GET .../models/{name}/versions/{n}/lineage``.

Answered from the apps' index snapshots: the digest/URI maps of
:class:`~vmn_exp.core.lineage.LineageIndex` are built once per snapshot and
shared by every request against it, so a lookup costs the linked runs, not
the workspace. A new generation's maps are moved along from the previous
one's by its row delta (rows compared by identity, see
:mod:`vmn_exp.ui.leaderboard_delta`), rebuilt when the delta is large; racing
requests share one build. The payloads are :func:`vmn_exp.sdk.reader.get_lineage`'s and
:func:`vmn_exp.registry.lineage.version_lineage`'s.
"""
import threading

from fastapi import HTTPException, Request

from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.core.lineage import DEFAULT_LIMIT, LineageIndex
from vmn_exp.core.status import derive_status
from vmn_exp.registry.lineage import run_lineage, version_lineage
from vmn_exp.registry.names import valid_model_name
from vmn_exp.ui.leaderboard_delta import changed_slots, delta_limit, left_rows
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.responses import json_response

MAX_DEPTH = 10
MAX_LIMIT = 1000
PER_APP = 2  # the indexes kept per app: its newest snapshots'


class _LineageIndexes:
    """A :class:`LineageIndex` per snapshot, each moved on from the app's
    latest (like :class:`~vmn_exp.ui.search_index.SearchIndexes`); the last
    :data:`PER_APP` of each app kept, so apps never evict each other."""

    def __init__(self):
        self._indexes = {}  # app -> LRU of its snapshots' indexes
        self._latest = {}  # app -> the LineageIndex built last
        self._lock = threading.Lock()

    def get(self, snapshot):
        """*snapshot*'s index; a schema view shares its base snapshot's."""
        snapshot = getattr(snapshot, "_base", None) or snapshot
        with self._lock:
            indexes = self._indexes.get(snapshot.app_name)
            if indexes is None:
                indexes = self._indexes[snapshot.app_name] = LRU(PER_APP)
        return indexes.per_snapshot(snapshot, lambda: self._built(snapshot))

    def _built(self, snapshot):
        with self._lock:
            prev = self._latest.get(snapshot.app_name)
        outputs_of = _outputs_reader(snapshot.outputs)  # never the snapshot: held weakly
        index = (prev and _moved(prev, snapshot, outputs_of)) or LineageIndex(snapshot.rows, outputs_of)
        with self._lock:
            self._latest[snapshot.app_name] = index
        return index


_INDEXES = _LineageIndexes()


def lineage_index(snapshot):
    """The :class:`LineageIndex` of *snapshot*, built on first use."""
    return _INDEXES.get(snapshot)


def _outputs_reader(outputs):
    """``IndexSnapshot.outputs_of`` over its *outputs* table alone."""
    return lambda verstr: outputs.get(verstr) or {}


def _moved(prev, snapshot, outputs_of):
    """*prev* moved to *snapshot*'s rows, or None when a verstr repeats or
    the delta is large."""
    rows, old = snapshot.rows, prev.row_list
    if len(snapshot.edges) != len(rows) or len(prev.rows) != len(old):
        return None
    slots = changed_slots(rows, old, delta_limit(rows))
    if slots is None:
        return None
    joined = [rows[i] for i in slots]
    return LineageIndex.moved(prev, rows, outputs_of, joined, left_rows(rows, old, slots))


class _Apps:
    """Per-request memo of the snapshots lineage touches (the run's app and
    any app a ``vmn://`` input names)."""

    def __init__(self, snapshot_for):
        self._snapshot_for, self._snapshots = snapshot_for, {}

    def snapshot(self, app_name):
        if app_name not in self._snapshots:
            self._snapshots[app_name] = self._snapshot_for(app_name)
        return self._snapshots[app_name]

    def index_for(self, app_name):
        return lineage_index(self.snapshot(app_name))

    def status_of(self, app_name, verstr):
        snap = self.snapshot(app_name)
        return derive_status(
            snap.run_states.get(verstr), observed_at=snap.run_state_observed_at.get(verstr)
        )


def _checked(depth, limit):
    if not 1 <= depth <= MAX_DEPTH:
        raise HTTPException(400, f"depth must be 1..{MAX_DEPTH}")
    if not 1 <= limit <= MAX_LIMIT:
        raise HTTPException(400, f"limit must be 1..{MAX_LIMIT}")


def register(app, prefix, lineage_inputs, segment, registry_of):
    """Add the route; *lineage_inputs(ws_name, app_tag)* →
    ``(app_name, snapshot_for(app_name), storage)``, *segment(verstr)* returns
    a URL verstr or raises a 400, *registry_of(storage)* the
    :class:`~vmn_exp.ui.registry_snapshot.RegistrySnapshot` to read."""

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}/lineage", dependencies=[require(VIEWER)])
    def experiment_lineage(
        request: Request,
        ws_name: str,
        app_tag: str,
        verstr: str,
        depth: int = 1,
        limit: int = DEFAULT_LIMIT,
    ):
        segment(verstr)
        _checked(depth, limit)
        app_name, snapshot_for, storage = lineage_inputs(ws_name, app_tag)
        apps = _Apps(snapshot_for)
        try:
            found = run_lineage(
                storage, app_name, verstr, apps.index_for, depth=depth, limit=limit,
                status_of=apps.status_of, registry=registry_of(storage),
            )
        except KeyError as e:
            raise HTTPException(404, e.args[0])
        return json_response(found, request=request)


def register_version_lineage(app, prefix, workspace_inputs, registry_of):
    """Add ``GET .../models/{name}/versions/{n}/lineage``; *workspace_inputs(ws_name)*
    → ``(snapshot_for(app_name), storage)``, *registry_of* as :func:`register`'s."""

    @app.get(f"{prefix}/workspaces/{{ws_name}}/models/{{model_name}}/versions/{{n}}/lineage", dependencies=[require(VIEWER)])
    def version_lineage_route(request: Request, ws_name: str, model_name: str, n: int):
        if not valid_model_name(model_name):
            raise HTTPException(400, f"Invalid model name {model_name!r}")
        snapshot_for, storage = workspace_inputs(ws_name)
        apps = _Apps(snapshot_for)
        try:
            found = version_lineage(
                storage, model_name, n, index_for=apps.index_for, status_of=apps.status_of,
                registry=registry_of(storage),
            )
        except KeyError as e:
            raise HTTPException(404, e.args[0])
        return json_response(found, request=request)
