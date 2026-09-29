#!/usr/bin/env python3
"""``GET .../apps/{app}/experiments/{verstr}/lineage?depth=1&limit=100``.

Answered from the app's index snapshot: the digest/URI maps of
:class:`~vmn_exp.core.lineage.LineageIndex` are built once per snapshot and
shared by every request against it, so a lookup costs the linked runs, not
the workspace. The payload is :func:`vmn_exp.sdk.reader.get_lineage`'s.
"""
import weakref

from fastapi import HTTPException, Request

from vmn_exp.core.lineage import DEFAULT_LIMIT, LineageIndex, resolve_lineage
from vmn_exp.core.status import derive_status
from vmn_exp.registry.view import models_for_run
from vmn_exp.ui.responses import json_response

MAX_DEPTH = 10
MAX_LIMIT = 1000
_INDEXES = weakref.WeakKeyDictionary()  # IndexSnapshot -> LineageIndex


def lineage_index(snapshot):
    """The :class:`LineageIndex` of *snapshot*, built on first use."""
    index = _INDEXES.get(snapshot)
    if index is None:
        index = _INDEXES[snapshot] = LineageIndex(snapshot.rows, snapshot.outputs_of)
    return index


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


def register(app, prefix, lineage_inputs, segment):
    """Add the route; *lineage_inputs(ws_name, app_tag)* →
    ``(app_name, snapshot_for(app_name), storage)``, *segment(verstr)* returns
    a URL verstr or raises a 400."""

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}/lineage")
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
            found = resolve_lineage(
                app_name, verstr, apps.index_for, depth=depth, limit=limit,
                status_of=apps.status_of,
            )
        except KeyError as e:
            raise HTTPException(404, e.args[0])
        found.update(
            app=app_name, verstr=verstr, models=models_for_run(storage, app_name, verstr)
        )
        return json_response(found, request=request)
