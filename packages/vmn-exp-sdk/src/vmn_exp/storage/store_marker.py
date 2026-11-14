"""``store.yml``: the marker at a store root — core's
:mod:`version_stamp.store.marker` (docs/plans/37-s3-snapshot-store-in-core.md).

Core takes the time a writer stamps and waits on as parameters; this module is
the SDK callers' composition point that wires the real ``time`` functions and
keeps their ``check_store(storage, writer)`` / ``new_marker()`` signatures.
"""
import time

from version_stamp.store import marker as _core
from version_stamp.store.marker import (  # noqa: F401 - re-exported
    LAYOUT,
    MARKER,
    LocalRoot,
    MissingStoreError,
    ObjectRoot,
    StoreLayoutError,
    _lock,
    authoritative,
    forget_checked,
    require_store,
    root_of,
)


def new_marker():
    """The marker a writer creates now."""
    return _core.new_marker(time.time())


def check_store(storage, writer):
    """Core's :func:`~version_stamp.store.marker.check_store` on real time."""
    _core.check_store(storage, writer, time.time, time.monotonic, time.sleep)
