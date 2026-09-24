#!/usr/bin/env python3
"""The log half of local-first storage with a remote (:mod:`snapshot_storage_cached`).

A writer's log exists in up to two copies: the local file its host appends to
and the remote objects that host ships as segments. Both only ever grow, and
the remote one is a prefix of the local one, so the bigger copy is the newer
one. Every read — listings, merged logs, the experiment index's per-file reads
— takes each writer from that same copy, so an incremental fold of the listed
files always equals a full re-read.
"""

import threading

from version_stamp.cli.snapshot_storage_files import (
    LEGACY_LOG_FILE,
    flatten_logs,
    is_log_file,
    log_object_name,
    log_sizes_of,
    log_writer_and_seq,
)
from version_stamp.core.experiment_status import load_run_state
from version_stamp.core.logging import VMN_LOGGER

LOCAL, REMOTE = "local", "remote"


def is_any_log(name):
    return name == LEGACY_LOG_FILE or is_log_file(name)


def log_writer(name):
    return "" if name == LEGACY_LOG_FILE else log_writer_and_seq(name)[0]


def pick_log_sources(remote_sizes, local_sizes):
    """``{writer: LOCAL | REMOTE}``: the copy of each writer's log to read.

    The bigger copy is the newer one; a tie goes to the local copy (no
    download). The legacy ``log.yml`` is read local-first, like any file.
    """
    sources = {}
    for writer in set(remote_sizes) | set(local_sizes):
        size = local_sizes.get(writer)
        newest = size is not None and (
            writer == "" or size >= remote_sizes.get(writer, 0)
        )
        sources[writer] = LOCAL if newest else REMOTE
    return sources


def _sizes(files):
    return log_sizes_of((name, sig[0]) for name, sig in files.items())


class CachedLogs:
    # Whether local log files are complete copies of their writers' logs
    # (False for a buffer that only holds what this process appended).
    _local_is_replica = True

    def _init_logs(self):
        # (app, verstr, writer) -> (bytes already on the remote, next segment)
        self._synced = {}
        # (app, verstr, writer) -> LOCAL | REMOTE, as the last listing chose
        self._log_sources = {}
        self._sync_lock = threading.Lock()
        self._compacted = set()  # writers already compacted after their run finished

    # -- listings ---------------------------------------------------------------

    def _merge_record_files(self, app_name, verstr, remote_files, local_files):
        """One record's listing: non-log files local-first, each writer's log
        files from the copy :func:`pick_log_sources` picks (remembered, so
        :meth:`read_file_from` reads what was listed)."""
        merged = {n: sig for n, sig in remote_files.items() if not is_any_log(n)}
        merged.update((n, sig) for n, sig in local_files.items() if not is_any_log(n))
        sources = pick_log_sources(_sizes(remote_files), _sizes(local_files))
        for writer, source in sources.items():
            self._log_sources[(app_name, verstr, writer)] = source
            chosen = local_files if source == LOCAL else remote_files
            merged.update(
                (n, sig)
                for n, sig in chosen.items()
                if is_any_log(n) and log_writer(n) == writer
            )
        return merged

    def read_file_from(self, app_name, verstr, filename, offset):
        """*filename* from *offset*, from the copy the last listing picked."""
        writer = log_writer(filename) if is_any_log(filename) else None
        default = LOCAL if self._local_is_replica else REMOTE
        source = self._log_sources.get((app_name, verstr, writer), default)
        if source == REMOTE and self._remote:
            return self._remote.read_file_from(app_name, verstr, filename, offset)
        data = self._local.read_file_from(app_name, verstr, filename, offset)
        if data is None and self._remote:
            return self._remote.read_file_from(app_name, verstr, filename, offset)
        return data

    # -- whole-log reads -----------------------------------------------------

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        return self.append_log_entries(app_name, verstr, writer_id, [entry])

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        # Local only: sync_log_to_remote ships the new bytes periodically.
        if not self._ensure_local_record(app_name, verstr):
            return False
        return self._local.append_log_entries(app_name, verstr, writer_id, entries)

    def _local_logs(self, app_name, verstr):
        if not self._local_is_replica:
            return {}
        return self._local.load_logs_by_writer(app_name, verstr)

    def load_logs_by_writer(self, app_name, verstr):
        """Per-writer logs; a remote failure raises rather than dropping writers."""
        local_logs = self._local_logs(app_name, verstr)
        return self._with_newer_remote_writers(app_name, verstr, local_logs)

    def load_merged_log(self, app_name, verstr):
        """The merged log for display: best effort when the remote fails."""
        local_logs = self._local_logs(app_name, verstr)
        if not any(local_logs.values()):
            return (
                self._remote.load_merged_log(app_name, verstr) if self._remote else []
            )
        try:
            local_logs = self._with_newer_remote_writers(app_name, verstr, local_logs)
        except Exception:
            VMN_LOGGER.debug(
                "Remote log read failed; showing the local log", exc_info=True
            )
        return flatten_logs(local_logs)

    def _with_newer_remote_writers(self, app_name, verstr, local_logs):
        """*local_logs* plus each writer whose remote copy is the bigger one:
        writers the remote merely mirrors are never downloaded."""
        logs = dict(local_logs)
        if not self._remote:
            return logs
        local_sizes = (
            self._local.log_sizes(app_name, verstr) if self._local_is_replica else {}
        )
        remote_sizes = dict(self._remote.log_sizes(app_name, verstr))
        sources = pick_log_sources(remote_sizes, local_sizes)
        newer = [w for w, source in sources.items() if source == REMOTE]
        if newer:
            logs.update(self._remote.load_logs_by_writer(app_name, verstr, newer))
        return logs

    # -- shipping to the remote -------------------------------------------------

    def _remote_log_state(self, app_name, verstr, writer_id):
        objects = list(self._remote.log_objects(app_name, verstr, writer_id))
        offset = sum(size for _, size in objects)
        seqs = [log_writer_and_seq(name)[1] for name, _ in objects]
        return offset, (max(seqs) + 1 if seqs else 0)

    def _initial_sync_state(self, app_name, verstr, writer_id):
        """Where shipping resumes: past everything the remote already holds."""
        return self._remote_log_state(app_name, verstr, writer_id)

    def _ship(self, app_name, verstr, writer_id, seq, chunk):
        """Upload *chunk* as segment *seq*; returns the seq it went to."""
        self._remote.save_file(app_name, verstr, log_object_name(writer_id, seq), chunk)
        return seq

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        """Ship the writer's complete lines appended since the last sync; once
        the run has finished, compact what the remote holds for the writer."""
        if not self._remote:
            return
        with self._sync_lock:
            self._ship_new_lines(app_name, verstr, writer_id)
        key = (app_name, verstr, writer_id)
        if key not in self._compacted and self._run_finished(app_name, verstr):
            self._compact(app_name, verstr, writer_id)
            self._compacted.add(key)

    def _ship_new_lines(self, app_name, verstr, writer_id):
        base = log_object_name(writer_id)
        local_size = self._local.log_sizes(app_name, verstr).get(writer_id, 0)
        if not local_size:
            return
        key = (app_name, verstr, writer_id)
        if key not in self._synced:
            self._synced[key] = self._initial_sync_state(app_name, verstr, writer_id)
        offset, seq = self._synced[key]
        if offset > local_size:
            # The remote holds more than this host ever wrote: start over.
            data = self._complete_lines(app_name, verstr, base, 0)
            if data:
                self._remote.save_file(app_name, verstr, base, data)
                self._remote.delete_log_segments(app_name, verstr, writer_id)
                self._synced[key] = (len(data), 1)
            return
        chunk = self._complete_lines(app_name, verstr, base, offset)
        if chunk:
            used = self._ship(app_name, verstr, writer_id, seq, chunk)
            self._synced[key] = (offset + len(chunk), used + 1)

    def _complete_lines(self, app_name, verstr, name, offset):
        """The complete lines of local *name* from *offset* on (b"" if none)."""
        data = self._local.read_file_from(app_name, verstr, name, offset) or b""
        return data[: data.rfind(b"\n") + 1]

    def _run_finished(self, app_name, verstr):
        state = load_run_state(self._local, app_name, verstr)
        return (state or {}).get("state") == "finished"

    def _compact(self, app_name, verstr, writer_id):
        compact = getattr(self._remote, "compact_log_segments", None)
        if compact is None:
            return
        try:
            compact(app_name, verstr, writer_id)
        except Exception:
            # Nothing is lost: the segments stay readable as they are.
            VMN_LOGGER.debug("Log compaction failed", exc_info=True)
