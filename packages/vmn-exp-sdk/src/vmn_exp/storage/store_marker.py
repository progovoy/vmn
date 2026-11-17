"""``store.yml``: the marker at a store root — core's
:mod:`version_stamp.store.marker` (docs/plans/45-s3-snapshot-store-in-core.md).

Core takes the time a writer stamps and waits on as parameters; this module
adapts the SDK's :class:`~vmn_exp.core.ports.Clock` its callers are handed.
"""
from vmn_exp.core.ports import wall_seconds
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


def new_marker(clock):
    """The marker a writer creates at *clock*'s now."""
    return _core.new_marker(wall_seconds(clock)())


def check_store(storage, writer, clock):
    """Core's :func:`~version_stamp.store.marker.check_store` on *clock*."""
    _core.check_store(storage, writer, wall_seconds(clock), clock.monotonic, clock.sleep)
