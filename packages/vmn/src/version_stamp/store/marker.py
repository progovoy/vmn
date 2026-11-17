"""``store.yml``: the marker at a store root (docs/plans/14-store-layout.md §2.3).

The first writer creates it with a create-if-absent put (``O_EXCL``-style
link locally, a plain ``O_EXCL`` create without hard links, ``If-None-Match``
on object stores). Writers and readers refuse a root of an unknown ``layout``,
a v1 root (no marker, and v1 records in it or in the v1 places outside it) and
a root with no marker holding anything but areas (not a vmn store, e.g.
``vmn snapshot --store /tmp``). An empty root (directory or prefix), or one with
only stray top-level files, is a fresh store: a writer marks it. Writers also
refuse while ``migrating`` is set.

A v1 record at the root is ``<name>/<rec>/`` under a non-area top-level
directory where ``<rec>`` holds a ``metadata.yml`` or is named like a verstr,
even with no files (what a crashed v1 write leaves). No single core parser
accepts every verstr a v1 store holds (``VMN_VERSION_REGEX`` refuses
``0.0.1.dev.abc`` and a non-hex dev hash), so a record name is one that, with
``_plus_`` read as ``+``, starts with ``VMN_VERSTR_REGEX``
(``X.Y.Z[.hotfix][-prerelease.rcn]``) and goes on, if at all, with ``.``,
``-`` or ``+`` (:func:`.marker_roots.is_record_name`).

The same checks and marker bytes as ``vmn_exp.storage.store_marker``, with the
time a writer stamps and waits on injected: ``check_store(storage, writer,
now, monotonic, sleep)`` (``now() -> epoch seconds`` for ``created_at``,
``monotonic()`` for the wait on another creator).
"""
import datetime

import yaml

from version_stamp.store import areas
from version_stamp.store.marker_roots import (  # noqa: F401 - re-exported
    MARKER,
    LocalRoot,
    ObjectRoot,
    StoreLayoutError,
    _publish_locked,
)
from version_stamp.store.per_process import PerProcessLock

LAYOUT = 2
_AREAS = {areas.RUNS, areas.SNAPSHOTS, areas.CODE, areas.SWEEPS, areas.REGISTRY,
          areas.REPORTS, areas.COMMENTS, areas.SETTINGS, areas.JOURNAL}

V1_STORE = (f"is a v1 store written by an older vmn-exp (records but no {MARKER}): "
            "run `vmn-exp migrate` (pip install vmn-exp)")
NOT_A_STORE = f"is not a vmn store (no {MARKER}, and its contents are not vmn records)"

_checked = set()
_lock = PerProcessLock()  # a forked child's own


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


def _foreign(where):
    """The root's top-level directories that are no area (dot ones are per-host
    state; stray files beside a store, e.g. a job's metadata file, are ignored)."""
    return {n for n in where.dirs() if n not in _AREAS and not n.startswith(".")}


def _is_v1(where, foreign):
    """v1 records: ``<root>/<name>/<verstr>/metadata.yml`` for a *foreign*
    top-level name, or in the v1 places outside the root (``has_v1_records``)."""
    return any(where.holds_records(n) for n in sorted(foreign)) or where.has_v1_records()


def _refuse_unmarked(where):
    """A root without a marker is a fresh store only if it holds nothing but areas."""
    foreign = _foreign(where)
    if _is_v1(where, foreign):
        raise StoreLayoutError(f"{_label(where)} {V1_STORE}")
    if foreign:
        raise StoreLayoutError(f"{_label(where)} {NOT_A_STORE}")


def _parse(text):
    marker = yaml.safe_load(text) if text else None
    return marker if isinstance(marker, dict) else {}


def check_store(storage, writer, now, monotonic, sleep):
    """Refuse *storage*'s root if it isn't a usable layout-2 store; a writer
    creates the marker when absent. Checked once per root and mode."""
    where = root_of(storage)
    if where is None:
        return
    cache_key = (where.key, writer)
    with _lock:
        if cache_key in _checked:
            return
    _check(where, writer, now, monotonic, sleep)
    with _lock:
        _checked.add(cache_key)


def _check(where, writer, now, monotonic, sleep):
    text = where.read()
    if text is None:
        _refuse_unmarked(where)
        if not writer:
            return
        where.create(yaml.safe_dump(new_marker(now()), sort_keys=False), monotonic, sleep)
        text = where.read()
    marker = _parse(text)
    if marker.get("layout") != LAYOUT:
        raise StoreLayoutError(
            f"{_label(where)} has store layout {marker.get('layout')}; this vmn "
            f"knows layout {LAYOUT} only: upgrade vmn")
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
    store at all. A reader never creates the marker, so needs no time."""
    backend = authoritative(storage)
    where = root_of(backend)
    if where is None:
        return
    if uri and where.read() is None and not any(
            not n.startswith(".") for n in where.entries()):
        raise MissingStoreError(f"no vmn store at {uri}")
    check_store(backend, writer=False, now=None, monotonic=None, sleep=None)


def authoritative(storage):
    """The storage that holds the authoritative records (the remote, if any)."""
    return getattr(storage, "_remote", None) or getattr(storage, "_local", None) or storage
