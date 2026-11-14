"""``store.yml``: the marker at a store root (docs/plans/14-store-layout.md §2.3).

The first writer creates it with a create-if-absent put (``O_EXCL``-style
link locally, a plain ``O_EXCL`` create without hard links, ``If-None-Match``
on object stores). Writers and readers refuse a root of an unknown ``layout``
and a v1 root (vmn records, no marker, also in the v1 places outside the root);
writers also refuse while ``migrating`` is set.

The same checks and marker bytes as ``vmn_exp.storage.store_marker``, with the
time a writer stamps and waits on injected: ``check_store(storage, writer,
clock, sleep)`` (``clock() -> epoch seconds``).
"""
import datetime

import yaml

from version_stamp.store import areas
from version_stamp.store.marker_roots import (  # noqa: F401 - re-exported
    MARKER,
    LocalRoot,
    ObjectRoot,
    _publish_locked,
)
from version_stamp.store.per_process import PerProcessLock

LAYOUT = 2
_AREAS = {areas.RUNS, areas.SNAPSHOTS, areas.CODE, areas.SWEEPS, areas.REGISTRY,
          areas.REPORTS, areas.COMMENTS, areas.SETTINGS, areas.JOURNAL}

_checked = set()
_lock = PerProcessLock()  # a forked child's own


class StoreLayoutError(ValueError):
    pass


class MissingStoreError(ValueError):
    pass


def forget_checked():
    with _lock:
        _checked.clear()


def new_marker(now):
    """The marker a writer creates at *now* (epoch seconds)."""
    created = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    return {"layout": LAYOUT, "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "journal": {"partition": "minute"}}


def root_of(storage):
    """The marker location of a backend storage, or None (unknown backend)."""
    if hasattr(storage, "root") and hasattr(storage, "area"):
        return LocalRoot(storage.root)
    if getattr(storage, "_s3", None) is None:
        return None
    return ObjectRoot(storage, storage.bucket, storage.prefix.rpartition("/")[0],
                      getattr(storage, "endpoint_url", None))


def _has_records(where):
    """v1 records live in ``<root>/<app>/<verstr>/`` (a top-level directory
    that is no area; stray files beside the store are not records) or in the
    v1 places outside the root (``where.has_v1_records``)."""
    if any(n not in _AREAS and not n.startswith(".") for n in where.dirs()):
        return True
    return where.has_v1_records()


def _parse(text):
    marker = yaml.safe_load(text) if text else None
    return marker if isinstance(marker, dict) else {}


def check_store(storage, writer, clock, sleep):
    """Refuse *storage*'s root if it isn't a usable layout-2 store; a writer
    creates the marker when absent. Checked once per root and mode."""
    where = root_of(storage)
    if where is None:
        return
    cache_key = (where.key, writer)
    with _lock:
        if cache_key in _checked:
            return
    _check(where, writer, clock, sleep)
    with _lock:
        _checked.add(cache_key)


def _check(where, writer, clock, sleep):
    text = where.read()
    if text is None:
        if _has_records(where):
            raise StoreLayoutError(
                f"{_label(where)} is a v1 store (records but no {MARKER}): "
                "run `vmn-exp migrate`")
        if not writer:
            return
        where.create(yaml.safe_dump(new_marker(clock()), sort_keys=False), clock, sleep)
        text = where.read()
    marker = _parse(text)
    if marker.get("layout") != LAYOUT:
        raise StoreLayoutError(
            f"{_label(where)} has store layout {marker.get('layout')}; this vmn-exp "
            f"knows layout {LAYOUT} only: upgrade vmn-exp")
    if writer and marker.get("migrating"):
        raise StoreLayoutError(
            f"{_label(where)} is migrating (`vmn-exp migrate`): retry when it is done")


def _label(where):
    if isinstance(where, LocalRoot):
        return where.root
    return f"{where.bucket}/{where.prefix}"


def require_store(storage, uri=None):
    """The reader's check of *storage*'s root: StoreLayoutError when it is
    unusable and, given its *uri*, MissingStoreError when it holds no vmn
    store at all. A reader never creates the marker, so needs no clock."""
    backend = authoritative(storage)
    where = root_of(backend)
    if where is None:
        return
    if uri and where.read() is None and not any(
            not n.startswith(".") for n in where.entries()):
        raise MissingStoreError(f"no vmn store at {uri}")
    check_store(backend, writer=False, clock=None, sleep=None)


def authoritative(storage):
    """The storage that holds the authoritative records (the remote, if any)."""
    return getattr(storage, "_remote", None) or getattr(storage, "_local", None) or storage
