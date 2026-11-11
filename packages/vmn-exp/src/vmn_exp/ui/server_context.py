"""The resolvers the UI routes share: the workspace, app and version a URL
names, each workspace's storages, and an app's settings and schema."""
import os

from fastapi import HTTPException
from vmn_exp.core.metric_schema import effective_schema
from vmn_exp.storage.areas import app_key
from vmn_exp.storage.store_marker import require_store
from vmn_exp.ui.api_errors import APP_NOT_FOUND, CodedError
from vmn_exp.ui.readers import experiments as exp_reader
from vmn_exp.ui.readers.contained_reads import ContainedReads
from vmn_exp.ui.security import safe_app_name, safe_segment
from vmn_exp.ui.storage_access import READ


class ServerContext:
    """Built once per app on its *manager* and experiment *source*.
    *open_workspace_storage(ws)* opens a store workspace's reader (raising
    ValueError for an unusable store), *open_edit_storage(uri)* its writer,
    *probe_store(uri)* finds the server's capabilities there and
    *app_exists(ws, app_name, storage)* checks an app with no rows yet."""

    def __init__(self, manager, source, app_lists, open_workspace_storage, open_edit_storage,
                 probe_store, app_exists):
        self.manager, self.source, self.app_lists = manager, source, app_lists
        self._open_workspace_storage = open_workspace_storage
        self._open_edit_storage = open_edit_storage
        self._probe_store = probe_store
        self._app_exists = app_exists
        # One client per store workspace: building one resolves credentials,
        # and its prefix probes are worth keeping across requests.
        self._store_storages = {}
        self._edit_storages = {}
        self._served_storages = {}  # id(storage) -> (storage, its ContainedReads)

    @staticmethod
    def app_name(app_tag):
        """The app name a URL names, refusing anything that walks out of .vmn/."""
        name = safe_app_name(app_tag)
        if name is None:
            raise HTTPException(400, f"Invalid app name '{app_tag}'")
        return name

    @staticmethod
    def segment(value, what="version"):
        if not safe_segment(value):
            raise HTTPException(400, f"Invalid {what} '{value}'")
        return value

    def optional_segment(self, value, what="version"):
        return None if value is None else self.segment(value, what)

    def workspace(self, name):
        ws = self.manager.get(name)
        if ws is None:
            raise HTTPException(404, f"Workspace '{name}' not found")
        return ws

    def git_workspace(self, name):
        ws = self.workspace(name)
        if ws.kind != "git":
            raise HTTPException(400, f"Workspace '{name}' is not a git checkout")
        return ws

    def exp_storage_for(self, ws):
        """The store workspace's experiment storage (memoized), or None for git."""
        if ws.kind == "git":
            return None  # None means: use the default path-based reader
        if ws.name not in self._store_storages:
            try:
                storage = self._open_workspace_storage(ws)
                require_store(storage, ws.store)
                self._store_storages[ws.name] = storage
            except ValueError as exc:  # no store there / an unusable one
                raise HTTPException(404, str(exc))
        return self._store_storages[ws.name]

    def any_exp_storage(self, ws):
        """The workspace's experiment storage, local checkout or store, read
        only inside each run's record dir (one wrapper per storage, so its
        cache identity holds)."""
        storage = self.exp_storage_for(ws) or self.source.workspace_index(ws).storage
        held = self._served_storages.get(id(storage))
        if held is None or held[0] is not storage:
            held = (storage, ContainedReads(storage, os.path.realpath))
            self._served_storages[id(storage)] = held
        return held[1]

    def ws_storage(self, ws_name):
        return self.any_exp_storage(self.workspace(ws_name))

    def capabilities(self, ws):
        if ws.capabilities is not None:
            return ws.capabilities
        capabilities = self._probe_store(ws.store).capabilities
        if READ in capabilities:  # an unreachable store is re-probed next time
            self.manager.set_capabilities(ws.name, capabilities)
        return capabilities

    def edit_storage(self, ws):
        if ws.name not in self._edit_storages:
            self._edit_storages[ws.name] = self._open_edit_storage(ws.store)
        return self._edit_storages[ws.name]

    def forget(self, ws_name):
        """Drop a removed workspace's app list and storages."""
        self.app_lists.pop(ws_name)
        self._store_storages.pop(ws_name, None)
        self._edit_storages.pop(ws_name, None)

    def list_apps(self, ws_name):
        ws = self.workspace(ws_name)
        store_storage = self.exp_storage_for(ws)
        if store_storage:
            # A remote store's runs are counted by its index (listing them is
            # slow); a file:// store lists them at once.
            counted = store_storage.is_remote()
            compute = lambda: exp_reader.list_apps_from_storage(  # noqa: E731
                store_storage, (lambda name: self.source.persisted_count(ws, name)) if counted else None)
        else:
            compute = lambda: exp_reader.list_apps(ws.path)  # noqa: E731
        return self.app_lists.get(ws_name, compute)

    def app_tags(self, ws_name):
        return [app_key(row["name"]) for row in self.list_apps(ws_name)]

    def settings(self, ws, app_name):
        """The app's store settings (plan 28 A0), below a git workspace's conf."""
        return self.source.app_settings(ws, app_name, self.any_exp_storage(ws))

    def app_schema(self, ws, app_name):
        """The app's metrics schema: conf.yml over the store settings."""
        return self.source.metrics_schema(ws, app_name, self.settings(ws, app_name))

    def from_settings(self, read):
        """``(ws_name, app_tag) -> read(ws, app_name, settings)``: one of the
        app's conf.yml values over its store settings."""
        def resolved(ws_name, app_tag):
            ws, app_name = self.workspace(ws_name), self.app_name(app_tag)
            return read(ws, app_name, self.settings(ws, app_name))
        return resolved

    def board_conf(self, snapshot):
        """``(metrics schema, experiment.ui)`` of *snapshot*'s app, as a request reads them."""
        owner = self.source.owner_of(snapshot)
        if owner is None:
            return {}, {}
        ws, app_name = owner
        settings = self.settings(ws, app_name)
        return (self.source.metrics_schema(ws, app_name, settings),
                self.source.experiment_ui(ws, app_name, settings))

    def app_inputs(self, ws_name, app_tag):
        """``(app name, snapshot, conf metrics schema)`` of an app: rows
        summarized by the conf schema (none in a store)."""
        ws, app_name = self.workspace(ws_name), self.app_name(app_tag)
        schema = self.app_schema(ws, app_name)
        return app_name, self.source.snapshot(ws, app_name, self.exp_storage_for(ws), schema), schema

    def leaderboard_inputs(self, ws_name, app_tag):
        """``(snapshot, effective metrics schema)`` of an app: sorted by the
        conf schema plus what the runs declare (see :mod:`vmn_exp.core.metric_schema`)."""
        _, snapshot, schema = self.app_inputs(ws_name, app_tag)
        return snapshot, effective_schema(schema, snapshot.declared_schema())

    def status_snapshot(self, ws_name, app_tag):
        """The app's snapshot; 404 ``app_not_found`` when there is no such app
        (an index still loading or re-deriving its records has one)."""
        app_name, snapshot, _ = self.app_inputs(ws_name, app_tag)
        ws = self.workspace(ws_name)
        if not snapshot.rows and snapshot.loading is None and not self._app_exists(
                ws, app_name, self.any_exp_storage(ws)):
            raise CodedError(404, f"App '{app_name}' not found", APP_NOT_FOUND)
        return snapshot

    def status_schema(self, ws_name, app_tag, snapshot):
        """The board's schema over the *snapshot* a status request already took."""
        schema = self.app_schema(self.workspace(ws_name), self.app_name(app_tag))
        return effective_schema(schema, snapshot.declared_schema())

    def app_scopes(self, ws_names):
        """``(ws_name, app_name, snapshot, conf schema)`` of every app of *ws_names*."""
        for ws_name in ws_names:
            ws = self.workspace(ws_name)
            for row in sorted(self.list_apps(ws_name), key=lambda r: r["name"]):
                name = row["name"]
                schema = self.app_schema(ws, name)
                yield ws_name, name, self.source.snapshot(ws, name, self.exp_storage_for(ws), schema), schema
