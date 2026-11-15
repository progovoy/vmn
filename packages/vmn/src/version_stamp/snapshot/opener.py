"""The snapshot store opener hook: vmn-exp registers the opener of its stores
(``version_stamp.api.register_snapshot_store_opener``, re-exported by
``version_stamp.cli.plugin_api``) and :mod:`.stores` asks it first."""
from typing import Callable, Optional

_snapshot_store_opener: Optional[Callable] = None


def register_snapshot_store_opener(fn: Callable) -> None:
    """Register *fn* as the opener of configured (remote) snapshot stores.

    ``fn(vcs, params) -> SnapshotStores | None`` (see
    ``version_stamp.snapshot.stores``); None means nothing is configured and
    the local stores apply. Registering again replaces the opener.
    """
    global _snapshot_store_opener
    _snapshot_store_opener = fn


def snapshot_store_opener() -> Optional[Callable]:
    """The registered snapshot store opener, or None (vmn-exp not installed)."""
    return _snapshot_store_opener
