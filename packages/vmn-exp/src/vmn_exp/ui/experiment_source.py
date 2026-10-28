#!/usr/bin/env python3
"""Where the server's experiment reads come from, per workspace.

Reads go through one :class:`IndexSnapshot` per request: the list pipeline,
the run tree's edges, ``latest``/``@N``/prefix refs and — with a background
refresher — the subtree's run states, so a request never lists the storage.
Git workspaces persist their index under ``<data_dir>/index``
(:class:`WorkspaceIndex`; in memory only with ``--no-index``), S3 workspaces
in a database of their own next to it, so a restarted server starts warm
either way. With a Postgres *cache_dsn* store workspaces are cached there
instead, shared by every replica (:mod:`vmn_exp.ui.pg_mode`). With
*search_rows* each refresh writes the app's Postgres search rows
(:mod:`vmn_exp.ui.search_rows_writer`).
"""
import os
import threading

import vmn_exp.core.index as experiment_index
from vmn_exp.core.app_settings import metrics_overlay, ui_overlay
from vmn_exp.core.index_point import shared_store
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.query_extra import bind_similar_scope
from vmn_exp.core.status import run_state_observed_at
from vmn_exp.storage.areas import app_key
from vmn_exp.ui import index as ui_index
from vmn_exp.ui.cache_health import SqliteHealth
from vmn_exp.ui.cache_resync import WorkspaceCache
from vmn_exp.ui.freshness import DEFAULT_STALE_AFTER_MIN, freshness
from vmn_exp.ui.leaderboard_group_fields import conf_aggregate
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers import experiments as exp_reader
from vmn_exp.ui.readers.baselines import last_good
from vmn_exp.ui.readers.branch_conf import app_conf_path
from vmn_exp.ui.refresher import InlineRefresher, NotingRefresher
from vmn_exp.ui.schema_cache import MetricsSchemaCache
from vmn_exp.ui.settings_cache import SettingsCache
from vmn_exp.ui.similar_corpora import SimilarCorpora

# A background server re-reads an app's store settings this often at most;
# a journal entry for them drops them at once.
SETTINGS_RECHECK_SEC = 60


def _state_reader(run_states):
    """A ``read_run_state`` answering from *run_states*, storage for the rest."""

    def read(storage, app_name, verstr):
        if verstr in run_states:
            return run_states[verstr]
        return exp_reader.load_run_state(storage, app_name, verstr)

    return read


def _observed_at_reader(observed_at):
    """A ``read_observed_at`` answering from *observed_at*, storage for the rest."""

    def read(storage, app_name, verstr):
        if verstr in observed_at:
            return observed_at[verstr]
        return run_state_observed_at(storage, app_name, verstr)

    return read


def _latest_memoized(snap):
    """*snap*'s ``resolve`` answering ``latest`` from a memo: finding it scans
    every row, and a run page polls it."""
    latest = []

    def resolve(ref):
        if ref not in ("latest", "@latest"):
            return snap.resolve(ref)
        if not latest:
            latest.append(snap.resolve(ref))
        return latest[0]

    return resolve


def _open_journal(ws, storage, cache_path):
    from vmn_exp.storage.journal_sinks import journal_list_fn
    from vmn_exp.ui.journal_follow import WorkspaceJournal

    try:
        list_fn = journal_list_fn(storage)
    except AttributeError:  # a backend without a journal sink
        return None
    return WorkspaceJournal(list_fn, SqliteStore(cache_path), ws.name)


class ExperimentSource:
    def __init__(self, data_dir, use_index=True, refresher=None, cache_dsn=None,
                 search_rows=None, store_upkeep=None):
        self._db_dir = os.path.join(data_dir, "index")
        # --no-index: git workspaces' indexes are kept in memory only.
        self._ws_db_dir = self._db_dir if use_index else None
        self.refresher = refresher or InlineRefresher()
        self._indexes = {}  # workspace name -> WorkspaceIndex
        self._journals = {}  # store workspace name -> WorkspaceJournal
        self._caches = {}  # workspace name -> WorkspaceCache
        self._served_by = {}  # (workspace name, app name) -> the index serving it
        self._resolvers = LRU(8)
        self._schemas = MetricsSchemaCache()
        self._conf_uis = MetricsSchemaCache(read=exp_reader.conf_ui, path=app_conf_path)
        # Inline refreshes see every write made before the request.
        self._settings = SettingsCache(SETTINGS_RECHECK_SEC if self.refresher.background else 0)
        self._lock = threading.Lock()
        self._search_rows = search_rows
        self._upkeep = store_upkeep
        if store_upkeep is not None:
            self.refresher.add_listener(store_upkeep.refreshed)
        # Where similar runs are searched, kept in step on every refresh.
        self.similar = SimilarCorpora(self._ws_db_dir)
        self.refresher.add_listener(self.similar.refreshed)
        if search_rows is not None:
            self.refresher.add_listener(search_rows.refreshed)
        self._pg = None
        if cache_dsn:
            from vmn_exp.ui.pg_mode import PgIndexes

            self._pg = PgIndexes(cache_dsn, self.refresher)

    def workspace_index(self, ws):
        """The git workspace's read cache (in memory only with ``--no-index``)."""
        with self._lock:
            if ws.name not in self._indexes:
                self._indexes[ws.name] = ui_index.WorkspaceIndex(ws.path, self._ws_db_dir)
            return self._indexes[ws.name]

    def snapshot(self, ws, app_name, s3_storage=None, schema=None):
        """The app's current :class:`IndexSnapshot`, its rows summarized by the
        metrics *schema* when one is given; a query's ``similar()`` over it
        searches the app's similar-runs scope."""
        snap = self._snapshot(ws, app_name, s3_storage, schema)
        key = (ws.name, app_name)
        bind_similar_scope(snap, lambda s: self.similar.scope(key, app_name, s))
        return snap

    def _snapshot(self, ws, app_name, s3_storage, schema):
        refresher = self._refresher_of(ws, app_name, s3_storage)
        if s3_storage is not None and self._pg is not None:
            return self._pg_snapshot(ws, app_name, s3_storage, schema, refresher)
        if s3_storage is not None:
            cache_path = ui_index.s3_cache_path(self._db_dir, ws)
            snap = ui_index.app_snapshot(
                s3_storage, app_name, cache_path, refresher, schema,
                self._journal(ws, s3_storage, cache_path), ws.reconcile_sec,
            )
            self._heal(ws, app_name, s3_storage, cache_path, lambda: experiment_index.shared_index(
                s3_storage, app_name, cache_path))
            return snap
        index = self.workspace_index(ws)
        snap = index.snapshot(app_name, refresher, schema)
        self._heal(ws, app_name, index.storage, index.db_path, lambda: index.index_of(app_name))
        return snap

    def _refresher_of(self, ws, app_name, s3_storage):
        """The refresher of *app_name*'s index, noting it for similar runs and
        the search rows."""
        def schema_of():
            storage = s3_storage if s3_storage is not None else self.workspace_index(ws).storage
            return self.metrics_schema(ws, app_name, self.app_settings(ws, app_name, storage))

        def note(index):
            self._served_by[(ws.name, app_name)] = index
            self.similar.note(index, (ws.name, app_name), app_name)
            if self._search_rows is not None:
                self._search_rows.note(index, ws.name, app_name, schema_of)
            if self._upkeep is not None and s3_storage is not None:
                self._upkeep.note(index, s3_storage, app_name)

        return NotingRefresher(self.refresher, note)

    def _pg_snapshot(self, ws, app_name, storage, schema, refresher):
        index = self._pg.index(ws, app_name, storage)
        journal = self._journal(ws, storage, ui_index.s3_cache_path(self._db_dir, ws))
        snap = ui_index.snapshot_of_index(index, storage, app_name, refresher, schema,
                                          journal, ws.reconcile_sec)
        self._heal(ws, app_name, storage, None, lambda: index)
        return snap

    def cache(self, ws, cache_path=None):
        """The workspace's :class:`WorkspaceCache` (resync, status, healing)."""
        with self._lock:
            if ws.name not in self._caches:
                self._caches[ws.name] = self._new_cache(ws, cache_path)
            return self._caches[ws.name]

    def caches(self):
        with self._lock:
            return dict(self._caches)

    def _new_cache(self, ws, cache_path):
        if self._pg is not None and ws.kind != "git":
            cache_path = None  # Postgres: no cache file to check or rebuild
        elif cache_path is None and ws.kind != "git":
            cache_path = ui_index.s3_cache_path(self._db_dir, ws)
        elif cache_path is None:
            cache_path = self._indexes[ws.name].db_path if ws.name in self._indexes else None
        health = SqliteHealth(cache_path) if cache_path else None
        # Inline refreshes check on every request, background ones per tick.
        cache = WorkspaceCache(ws.name, cache_path, health,
                               journal_of=lambda: self._journals.get(ws.name),
                               check_sec=getattr(self.refresher, "interval_sec", 0))
        if cache_path:
            cache.on_swapped(lambda: self._reopen(ws.name, cache_path))
        return cache

    def _reopen(self, ws_name, cache_path):
        """A rebuild renamed a new file over *cache_path*: reconnect to it."""
        journal = self._journals.get(ws_name)
        if journal is not None:
            journal.use_cache(SqliteStore(cache_path))
        if ws_name in self._indexes:
            self._indexes[ws_name].reopen()

    def _heal(self, ws, app_name, storage, cache_path, index_of):
        """Note what *app_name* is served from, and check the cache's health."""
        cache = self.cache(ws, cache_path)
        cache.note(app_name, storage, index_of)
        cache.tick()

    def _journal(self, ws, storage, cache_path):
        """The store workspace's journal reader (background refresh only)."""
        if not self.refresher.background:
            return None
        with self._lock:
            if ws.name not in self._journals:
                journal = _open_journal(ws, storage, cache_path)
                if journal is not None:
                    journal.on_settings(lambda key: self._settings.forget(ws.name, key))
                self._journals[ws.name] = journal
            return self._journals[ws.name]

    def journal_of(self, ws_name):
        """The store workspace's journal reader, once a snapshot opened it."""
        return self._journals.get(ws_name)

    def persisted_count(self, ws, app_name):
        """How many of the store workspace *ws*'s *app_name* records its
        index file holds, without reading storage; 0 when none (or Postgres)."""
        if self._pg is not None:
            return 0
        return shared_store(ui_index.s3_cache_path(self._db_dir, ws)).count(app_name)

    def touched(self, ws, app_name, s3_storage):
        """A server edit changed *app_name* in the store workspace *ws*."""
        if self._pg is not None:
            self._pg.index(ws, app_name, s3_storage).refresh()
            return
        ui_index.refresh_app(s3_storage, app_name, ui_index.s3_cache_path(self._db_dir, ws))

    def app_settings(self, ws, app_name, storage):
        """The app's store settings in *storage* (:mod:`vmn_exp.core.app_settings`)."""
        return self._settings.get(ws.name, storage, app_name)

    def settings_changed(self, ws, app_name):
        """This server wrote the app's settings: read them again."""
        self._settings.forget(ws.name, app_key(app_name))

    def metrics_schema(self, ws, app_name, settings=None):
        """The app's metrics schema: a git workspace's conf (parsed once per
        conf change) over its *settings*."""
        conf = self._schemas.get(ws.path, app_name) if ws.kind == "git" else {}
        return metrics_overlay(settings, conf)

    def experiment_ui(self, ws, app_name, settings=None):
        """The app's ``experiment.ui``: a git workspace's branch conf over *settings*."""
        conf = self._conf_uis.get(ws.path, app_name) if ws.kind == "git" else {}
        return ui_overlay(settings, conf)

    def group_aggregate(self, ws, app_name, settings=None):
        """The app's default group aggregate (plan 22 G10)."""
        return conf_aggregate(self.experiment_ui(ws, app_name, settings))

    def stale_after_min(self, ws, app_name, settings=None):
        """The app's ``experiment.ui.stale_after_min``, else the default."""
        return exp_reader.stale_after_of(self.experiment_ui(ws, app_name, settings))

    def split_by(self, ws, app_name, settings=None):
        """The app's ``experiment.ui.split_by`` (plan 28 P3), else None."""
        return exp_reader.split_by_of(self.experiment_ui(ws, app_name, settings))

    def detail_options(self, ws, snap):
        """``edges``/``resolve``/``read_child_row``/``last_good`` (and with a background
        refresher ``read_run_state``/``read_observed_at``) for a
        run-detail read."""
        # The same edges mapping per snapshot, so the children index is reused.
        options = {
            "edges": lambda storage, app_name: snap.edges,
            "resolve": self._resolvers.per_snapshot(snap, lambda: _latest_memoized(snap)),
            "read_child_row": lambda verstr: snap.row(verstr),
            "last_good": lambda verstr: last_good(snap, verstr),
        }
        if self.refresher.background:
            # A refreshed-inline snapshot leaves the subtree's states to be
            # read from storage; a background one's are at most ~1s old.
            options["read_run_state"] = _state_reader(snap.run_states)
            options["read_observed_at"] = _observed_at_reader(snap.run_state_observed_at)
        return options

    def freshness(self, ws_name, app_name, stale_after_min=DEFAULT_STALE_AFTER_MIN):
        """How fresh the index a snapshot of the app was last served from is
        (:mod:`vmn_exp.ui.freshness`); None before one, or inline."""
        index = self._served_by.get((ws_name, app_name))
        health = None if index is None else self.refresher.health(index)
        if health is None:
            return None
        return freshness(health, index.freshness(), stale_after_min)

    def forget(self, ws_name):
        """Drop a removed workspace's caches: a later one may point elsewhere."""
        with self._lock:
            for key in [k for k in self._served_by if k[0] == ws_name]:
                del self._served_by[key]
            self._indexes.pop(ws_name, None)
            self._journals.pop(ws_name, None)
            self._caches.pop(ws_name, None)
        self._settings.forget(ws_name)
        if self._pg is not None:
            self._pg.forget(ws_name)
