"""A log buffer dir its owner left behind, opened again to ship what it
holds (plan 40 C6; ``BufferedRemoteStorage.reopen``)."""
from vmn_exp.storage.cached import CachedSnapshotStorage


class ReopenedBuffer(CachedSnapshotStorage):
    """Every stream in the dir is its own, under the owner it was written
    with: no new owner is minted. It takes no owner lock (its shipper holds
    the dir's), is never part of the exit flush, never removes the dir and
    ships as a final flush does (no live roll-up; a finished run's streams
    are compacted)."""

    _local_is_replica = False
    _final_flush = True

    def _stream_owned(self, app_name, verstr):
        return lambda stream: True
