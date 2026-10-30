"""The model registry as the lineage routes read it: one in-memory
:class:`RegistrySnapshot` per store, so a lineage request reads no store.

Walking the registry per request cost a listing per model plus, whenever
any model changed, every model's header, log and version ``metadata.yml``
(on a big S3 store: 336 listings and 1,630 GETs, 201 s). Here a refresh
lists the registry (a listing per model) and re-reads only the models whose
files changed; requests answer from the last snapshot.

With background refresh (what ``vmn-exp ui`` runs) the first request
builds the snapshot — racing requests share that build — and later ones
start a refresh on a daemon thread at most every :data:`REFRESH_SEC`,
reading the snapshot as it is; else each request refreshes first, so it
sees every write before it — like the experiment indexes.
"""
import logging
import threading
import time
import weakref

from vmn_exp.core.activity import activity
from vmn_exp.registry.fold import fold_registry
from vmn_exp.registry.log import read_entries, read_uses
from vmn_exp.registry.names import HEADER_RECORD, USES_RECORD, valid_model_name
from vmn_exp.registry.store import (
    get_version, header_kind, list_versions, load_header, registry_storage, run_of,
)
from vmn_exp.registry.view import version_entry
from vmn_exp.storage.files import METADATA_FILE
from vmn_exp.storage.s3_base import parallel_map

REFRESH_SEC = 30.0

_LOGGER = logging.getLogger(__name__)


class _Model:
    """One model's registry state, read when its *files* listing changes."""

    __slots__ = ("files", "header", "fold", "versions", "uses")

    def __init__(self, storage, name, files):
        records = {r for r, f in files.items() if METADATA_FILE in f}
        self.files = files
        self.header = load_header(storage, name) if HEADER_RECORD in records else None
        self.fold = fold_registry(read_entries(storage, name) if HEADER_RECORD in records else [])
        self.uses = read_uses(storage, name) if USES_RECORD in records else {}
        self.versions = {n: get_version(storage, name, n)
                         for n in list_versions(storage, name, records)}


class RegistrySnapshot:
    """The lookups of :class:`vmn_exp.registry.lineage.RegistryLinks`,
    answered from memory. Never mutated once built."""

    def __init__(self, models):
        self._models = models
        self._run_models = _run_models(models)

    @classmethod
    def read(cls, storage, previous=None):
        """*storage*'s registry, reusing *previous*'s unchanged models."""
        reg = registry_storage(storage)
        names = [name for name in reg.list_apps() if valid_model_name(name)]
        listings = parallel_map(reg.list_files, names)
        old = previous._models if previous is not None else {}

        def model(item):
            name, files = item
            kept = old.get(name)
            return kept if kept is not None and kept.files == files else _Model(storage, name, files)

        return cls(dict(zip(names, parallel_map(model, list(zip(names, listings))))))

    def models_of(self, app, verstr):
        return self._run_models.get((app, verstr), ())

    def version_live(self, name, n):
        return self.version(name, n) is not None and self.status(name, n) != "deleted"

    def version(self, name, n):
        model = self._models.get(name)
        return model.versions.get(n) if model else None

    def kind(self, name):
        model = self._models.get(name)
        return header_kind(model.header) if model else None

    def status(self, name, n):
        model = self._models.get(name)
        return model.fold["status"].get(n, "active") if model else "active"

    def uses(self, name, n):
        model = self._models.get(name)
        return model.uses.get(n, []) if model else []


def _run_models(models):
    """``{(app, verstr): [version entry]}`` like :func:`vmn_exp.registry.view.run_models`."""
    found = {}
    for name in sorted(models):
        model = models[name]
        if model.header is None:
            continue
        kind = header_kind(model.header)
        for n, meta in sorted(model.versions.items()):
            run = run_of(meta)
            if run is not None and model.fold["status"].get(n) != "deleted":
                found.setdefault(run, []).append(version_entry(name, kind, n, meta, model.fold))
    return found


class _Entry:
    def __init__(self):
        self.snapshot, self.at, self.refreshing = None, None, False
        self.lock = threading.Lock()  # one build at a time


class RegistrySnapshots:
    """A :class:`RegistrySnapshot` per storage, refreshed as configured."""

    def __init__(self, background=False):
        self._background = background
        self._entries = weakref.WeakKeyDictionary()  # storage -> _Entry
        self._lock = threading.Lock()

    def get(self, storage):
        with self._lock:
            entry = self._entries.get(storage)
            if entry is None:
                entry = self._entries[storage] = _Entry()
        if not self._background or entry.snapshot is None:
            with entry.lock:
                if not self._background or entry.snapshot is None:
                    _refresh(storage, entry)
            return entry.snapshot
        self._refresh_when_due(storage, entry)
        return entry.snapshot

    def _refresh_when_due(self, storage, entry):
        with self._lock:
            if entry.refreshing or time.monotonic() - entry.at < REFRESH_SEC:
                return
            entry.refreshing = True
        threading.Thread(target=self._refresh_later, args=(storage, entry), daemon=True,
                         name="vmn-ui-registry").start()

    def _refresh_later(self, storage, entry):
        try:
            with activity("registry snapshot refresh"), entry.lock:
                _refresh(storage, entry)
        except Exception:
            _LOGGER.warning("Refreshing the registry snapshot failed", exc_info=True)
        finally:
            with self._lock:
                entry.at, entry.refreshing = time.monotonic(), False


def _refresh(storage, entry):
    entry.snapshot = RegistrySnapshot.read(storage, entry.snapshot)
    entry.at = time.monotonic()
