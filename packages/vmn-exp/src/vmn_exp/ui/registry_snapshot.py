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

With background refresh this snapshot and the Models list's
(:class:`~vmn_exp.ui.readers.models.ModelListing`) share one registry
listing per refresh (:class:`RegistryListings`); each still builds its own
models from it.
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
    complete_records, get_versions, header_kind, list_versions, load_header, registry_storage,
    run_of,
)
from vmn_exp.registry.view import by_location, version_entry
from vmn_exp.storage.s3_base import parallel_map

REFRESH_SEC = 30.0

_LOGGER = logging.getLogger(__name__)


class _Model:
    """One model's registry state, read when its *files* listing changes."""

    __slots__ = ("files", "header", "fold", "versions", "uses")

    def __init__(self, storage, name, files):
        records = complete_records(files)
        self.files = files
        self.header = load_header(storage, name) if HEADER_RECORD in records else None
        self.fold = fold_registry(read_entries(storage, name) if HEADER_RECORD in records else [])
        self.uses = read_uses(storage, name) if USES_RECORD in records else {}
        self.versions = get_versions(storage, name, list_versions(storage, name, records))


def list_registry(storage):
    """``{model: files}``: the listing of each model of *storage*'s registry."""
    reg = registry_storage(storage)
    names = [name for name in reg.list_apps() if valid_model_name(name)]
    return dict(zip(names, parallel_map(reg.list_files, names)))


def read_models(storage, old, build, listing=None):
    """``{model: build(storage, name, files)}`` of every model of *storage*'s
    registry (*files*: its *listing*, by default listed now), each built
    concurrently; an entry of *old* (a dict like it, or None) whose
    ``files`` still match is kept."""
    old = old or {}
    listing = list_registry(storage) if listing is None else listing

    def model(item):
        name, files = item
        kept = old.get(name)
        return kept if kept is not None and kept.files == files else build(storage, name, files)

    return dict(zip(listing, parallel_map(model, list(listing.items()))))


class RegistrySnapshot:
    """The lookups of :class:`vmn_exp.registry.lineage.RegistryLinks`,
    answered from memory. Never mutated once built."""

    def __init__(self, models):
        self._models = models
        self._run_models = _run_models(models)
        self._locations = by_location(self._run_models)

    @classmethod
    def read(cls, storage, previous=None, listing=None):
        """*storage*'s registry (from *listing*, see :func:`read_models`),
        reusing *previous*'s unchanged models."""
        return cls(read_models(storage, previous and previous._models, _Model, listing))

    def models_of(self, app, verstr):
        return self._run_models.get((app, verstr), ())

    def location_versions(self, uri):
        return self._locations.get(uri, ())

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
    """A snapshot per storage — ``read(storage, previous, listing)``'s, by
    default a :class:`RegistrySnapshot` — refreshed as configured. With
    background refresh it reads the registry listing through *listings* (a
    :class:`RegistryListings` the other snapshots of the server share), and
    a snapshot is as old as its listing."""

    def __init__(self, background=False, read=RegistrySnapshot.read, listings=None):
        self._background = background
        self._read = read
        self._listings = listings if background else None
        self._entries = weakref.WeakKeyDictionary()  # storage -> _Entry
        self._lock = threading.Lock()

    def get(self, storage):
        entry = self._entry(storage)
        if not self._background or entry.snapshot is None:
            with entry.lock:
                if not self._background or entry.snapshot is None:
                    self._refresh(storage, entry)
            return entry.snapshot
        self._refresh_when_due(storage, entry)
        return entry.snapshot

    def refresh_model(self, storage, name):
        """Re-read model *name* of *storage*'s snapshot now (after this
        server wrote to it), and drop the shared listing that predates the
        write; without background refresh, the next ``get`` reads it anyway."""
        if self._listings is not None:
            self._listings.forget(storage)
        entry = self._entry(storage)
        with entry.lock:
            if self._background and entry.snapshot is not None:
                entry.snapshot = entry.snapshot.with_model(storage, name)

    def _entry(self, storage):
        with self._lock:
            entry = self._entries.get(storage)
            if entry is None:
                entry = self._entries[storage] = _Entry()
            return entry

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
                self._refresh(storage, entry)
        except Exception:
            _LOGGER.warning("Refreshing the registry snapshot failed", exc_info=True)
            entry.at = time.monotonic()
        finally:
            with self._lock:
                entry.refreshing = False

    def _refresh(self, storage, entry):
        if self._listings is None:
            at, listing = time.monotonic(), None
        else:
            at, listing = self._listings.get(storage)
        entry.snapshot = self._read(storage, entry.snapshot, listing)
        entry.at = at


class _Listing:
    def __init__(self):
        self.listing, self.at, self.generation = None, None, 0
        self.lock = threading.Lock()  # one listing at a time


class RegistryListings:
    """One registry listing (:func:`list_registry`) per storage, shared by the
    snapshots refreshed from it: one younger than :data:`REFRESH_SEC` is
    reused, racing reads wait for one listing, and :meth:`forget` (a write
    through this server) drops it — and any listing in flight then."""

    def __init__(self):
        self._entries = weakref.WeakKeyDictionary()  # storage -> _Listing
        self._lock = threading.Lock()

    def get(self, storage):
        """``(monotonic time it was taken, listing)`` of *storage*'s registry."""
        entry = self._entry(storage)
        with entry.lock:
            with self._lock:
                if entry.listing is not None and time.monotonic() - entry.at < REFRESH_SEC:
                    return entry.at, entry.listing
            while True:
                generation, at = entry.generation, time.monotonic()
                listing = list_registry(storage)
                with self._lock:
                    if entry.generation == generation:
                        entry.listing, entry.at = listing, at
                        return at, listing

    def forget(self, storage):
        entry = self._entry(storage)
        with self._lock:
            entry.listing, entry.generation = None, entry.generation + 1

    def _entry(self, storage):
        with self._lock:
            entry = self._entries.get(storage)
            if entry is None:
                entry = self._entries[storage] = _Listing()
            return entry
