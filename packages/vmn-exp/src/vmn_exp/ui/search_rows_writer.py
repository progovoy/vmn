#!/usr/bin/env python3
"""Keeps ``vmn_search_rows`` current from index refreshes (plan 25 F5).

:class:`~vmn_exp.ui.experiment_source.ExperimentSource` notes the index
serving each workspace app (:meth:`SearchRowsWriter.note`). After every
refresh (a refresher listener, :meth:`SearchRowsWriter.refreshed`) the
writer writes that app's rows when its snapshot's generation (or metrics
schema) moved — only the rows whose stored JSON or position changed since its
last write, and deletes the removed ones (a first write is a full sync) — on
the replica leading the index only (an
:class:`~vmn_exp.ui.elected_index.ElectedIndex`'s ``leading``; any other index
has no election, so its replica writes). Generations are per process: a
replica that takes the lead back writes again whatever it wrote before.
"""
import hashlib
import logging
import threading

from vmn_exp.core.index_views import schema_key
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui.search_pg import search_entries
from vmn_exp.ui.tenancy import current_org, org_context

_LOGGER = logging.getLogger(__name__)


def search_rows(snapshot):
    """The rows of *snapshot* a search answers with (statuses annotated)."""
    return annotate_rows(snapshot.rows, snapshot.run_states, snapshot.run_state_observed_at)


class SearchRowsWriter:
    def __init__(self, sql):
        self._sql = sql  # a PgRowSearch
        self._scopes = {}  # index -> (org, workspace, app, schema_of)
        self._written = {}  # index -> (generation, schema key)
        self._stored = {}  # index -> {verstr: (pos, digest of its JSON)} last written
        self._lock = threading.Lock()

    def note(self, index, workspace, app, schema_of):
        """*index* serves *workspace*/*app* of the request's org, its rows
        summarized by ``schema_of()``."""
        with self._lock:
            self._scopes[index] = (current_org(), workspace, app, schema_of)

    def refreshed(self, index, snapshot):
        """*index* was just refreshed to *snapshot*: write its rows if this
        replica leads it and they moved."""
        with self._lock:
            scope = self._scopes.get(index)
        if scope is None:
            return
        if not getattr(index, "leading", True):
            self._written.pop(index, None)
            self._stored.pop(index, None)
            return
        try:
            self._write(index, snapshot, *scope)
        except Exception:
            _LOGGER.warning("Writing search rows failed", exc_info=True)

    def _write(self, index, snapshot, org, workspace, app, schema_of):
        schema = schema_of()
        mark = (snapshot.generation, schema_key(schema))
        if self._written.get(index) == mark:
            return
        entries = search_entries(search_rows(snapshot.summarized(schema)))
        stored = {verstr: (pos, _digest(data)) for verstr, pos, data in entries}
        last = self._stored.get(index)
        with org_context(org):
            if last is None:
                self._sql.write(workspace, app, entries)
            else:
                changed = [e for e in entries if last.get(e[0]) != stored[e[0]]]
                removed = [verstr for verstr in last if verstr not in stored]
                if changed or removed:
                    self._sql.write(workspace, app, changed, removed)
        self._written[index] = mark
        self._stored[index] = stored


def _digest(data):
    return hashlib.blake2b(data.encode(), digest_size=16).digest()
