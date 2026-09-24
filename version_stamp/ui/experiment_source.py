#!/usr/bin/env python3
"""Where the server's experiment reads come from, per workspace.

Indexed reads go through one :class:`IndexSnapshot` per request: the list
pipeline, the run tree's edges, ``latest``/``@N``/prefix refs and — with a
background refresher — the subtree's run states, so a request never lists
the storage. Git workspaces persist their index under ``<data_dir>/index``
(:class:`WorkspaceIndex`), S3 workspaces in a database of their own next to
it, so a restarted server starts warm either way.
"""
import os
import threading

from version_stamp.core.experiment_index_snapshot import IndexSnapshot
from version_stamp.ui import index as ui_index
from version_stamp.ui.readers import experiment_detail as detail_reader
from version_stamp.ui.readers import experiments as exp_reader


def _state_reader(run_states):
    """A ``read_run_state`` answering from *run_states*, storage for the rest."""

    def read(storage, app_name, verstr):
        if verstr in run_states:
            return run_states[verstr]
        return exp_reader.load_run_state(storage, app_name, verstr)

    return read


class ExperimentSource:
    def __init__(self, data_dir, use_index=True, refresher=None):
        self._db_dir = os.path.join(data_dir, "index")
        self._use_index = use_index
        self.refresher = refresher
        self._indexes = {}  # workspace name -> WorkspaceIndex
        self._edges = {}  # workspace name -> ParentEdges, for unindexed reads
        self._lock = threading.Lock()

    def _workspace_index(self, ws):
        with self._lock:
            if ws.name not in self._indexes:
                self._indexes[ws.name] = ui_index.WorkspaceIndex(ws.path, db_dir=self._db_dir)
            return self._indexes[ws.name]

    def workspace_index(self, ws):
        """The git workspace's read cache, or None with ``--no-index``."""
        return self._workspace_index(ws) if self._use_index else None

    def snapshot(self, ws, app_name, s3_storage=None):
        """The app's current snapshot; None for an unindexed git workspace."""
        if s3_storage is not None:
            cache_path = ui_index.s3_cache_path(self._db_dir, ws)
            return ui_index.app_snapshot(s3_storage, app_name, cache_path, self.refresher)
        index = self.workspace_index(ws)
        return index.snapshot(app_name, self.refresher) if index else None

    def list_snapshot(self, ws, app_name, s3_storage=None):
        """Like :meth:`snapshot`, read directly when there is no index."""
        snap = self.snapshot(ws, app_name, s3_storage)
        if snap is not None:
            return snap
        rows, states = exp_reader.direct_rows_and_states(
            exp_reader.experiment_storage(ws.path), app_name
        )
        return IndexSnapshot.build(app_name, 0, rows, states)

    def detail_options(self, ws, snap):
        """``edges``/``resolve``/``read_run_state`` for a run-detail read."""
        if snap is None:
            with self._lock:
                return {"edges": self._edges.setdefault(ws.name, detail_reader.ParentEdges())}
        # The same edges mapping per snapshot, so the children index is reused.
        options = {"edges": lambda storage, app_name: snap.edges, "resolve": snap.resolve}
        if self.refresher is not None:
            # Inline refreshes read states fresh; a refresher's are ~1s old.
            options["read_run_state"] = _state_reader(snap.run_states)
        return options

    def forget(self, ws_name):
        """Drop a removed workspace's caches: a later one may point elsewhere."""
        with self._lock:
            self._indexes.pop(ws_name, None)
            self._edges.pop(ws_name, None)
