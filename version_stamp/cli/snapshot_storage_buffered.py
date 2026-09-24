#!/usr/bin/env python3
"""Direct-to-remote experiment storage whose logs are buffered locally.

A pod with a bucket and no scratch dir used to append each log entry by
reading the writer's whole log object back and rewriting it: quadratic in the
log's length. Here appends land in a private temp dir and ship as segments
(the local-first backend's machinery): the first append at once, later ones at
most every ``flush_interval_sec`` (a sooner sync — the run's heartbeat, its
finish, process exit — ships them earlier).

The buffer is not a replica: it holds only what this process appended, plus
the metadata that makes appends legal. Every read goes to the remote, and the
remote stays the only copy of a record's body.
"""

import atexit
import os
import shutil
import tempfile
import time
import uuid

from version_stamp.cli.snapshot_storage_cached import CachedSnapshotStorage
from version_stamp.cli.snapshot_storage_files import METADATA_FILE
from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import parse_record_metadata

DEFAULT_FLUSH_INTERVAL_SEC = 5


class BufferedRemoteStorage(CachedSnapshotStorage):
    _local_is_replica = False

    def __init__(
        self,
        remote,
        subdir="experiments",
        flush_interval_sec=DEFAULT_FLUSH_INTERVAL_SEC,
    ):
        # Created on the first write, so a read-only command leaves nothing behind.
        self._buffer_root = os.path.join(
            tempfile.gettempdir(), f"vmn-log-buffer-{uuid.uuid4().hex}"
        )
        super().__init__(LocalSnapshotStorage(self._buffer_root, subdir=subdir), remote)
        self._flush_interval_sec = flush_interval_sec
        self._flushed_at = {}
        atexit.register(self.close)

    def load(self, app_name, verstr):
        return self._remote.load(app_name, verstr)

    def load_file(self, app_name, verstr, filename):
        return self._remote.load_file(app_name, verstr, filename)

    def _ensure_local_record(self, app_name, verstr):
        """A home for appends: the record's metadata, never its body."""
        if self._local.exists(app_name, verstr):
            return True
        raw = self._remote.load_file(app_name, verstr, METADATA_FILE)
        metadata = parse_record_metadata(raw) if raw else None
        if metadata is None:
            return False
        self._local.save(app_name, verstr, metadata, {})
        return True

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        # Straight up: a multi-GB checkpoint must not be copied to /tmp first.
        if not self._ensure_local_record(app_name, verstr):
            return False
        return self._remote.save_artifact_file(app_name, verstr, src_path, name=name)

    # -- logs -------------------------------------------------------------------

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        if not super().append_log_entry(app_name, verstr, writer_id, entry):
            return False
        return self._ship_if_due(app_name, verstr, writer_id)

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        if not super().append_log_entries(app_name, verstr, writer_id, entries):
            return False
        return self._ship_if_due(app_name, verstr, writer_id)

    def _ship_if_due(self, app_name, verstr, writer_id):
        last = self._flushed_at.get((app_name, verstr, writer_id))
        if last is None or time.monotonic() - last >= self._flush_interval_sec:
            self.sync_log_to_remote(app_name, verstr, writer_id)
        return True

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        self._flushed_at[(app_name, verstr, writer_id)] = time.monotonic()
        super().sync_log_to_remote(app_name, verstr, writer_id)

    def _initial_sync_state(self, app_name, verstr, writer_id):
        # The buffer starts empty: ship all of it, after what the remote holds
        # (another process of this host may have logged under the same writer).
        _, seq = self._remote_log_state(app_name, verstr, writer_id)
        return 0, seq

    def _ship(self, app_name, verstr, writer_id, seq, chunk):
        return self._remote.put_log_segment(app_name, verstr, writer_id, seq, chunk)

    def close(self):
        """Ship whatever is still buffered and drop the buffer."""
        for app_name, verstr, writer_id in list(self._flushed_at):
            try:
                self.sync_log_to_remote(app_name, verstr, writer_id)
            except Exception:
                VMN_LOGGER.warning(
                    f"Experiment {verstr}: could not ship the last log lines"
                )
                VMN_LOGGER.debug("Final log flush failed", exc_info=True)
        # A later append starts a fresh buffer, shipped from its first byte.
        self._flushed_at.clear()
        self._synced.clear()
        shutil.rmtree(self._buffer_root, ignore_errors=True)
