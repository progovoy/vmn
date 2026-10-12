#!/usr/bin/env python3
"""The log half of local-first storage with a remote (:mod:`snapshot_storage_cached`).

A stream's log (:mod:`vmn_exp.core.streams`) exists in up to two copies: the
local file of the record copy that owns it — the only one that appends to it
— and the remote objects shipped from that file. Both only ever grow and the
remote one is a replica of a prefix of the local one, so shipping resumes
exactly past the bytes the remote holds (:mod:`ship_state`). A copy ships and
compacts only the streams it owns (its current and retired owners'), plus
the missing part of those it inherited (:mod:`stream_owner`). Every read —
listings, merged logs, the experiment index's per-file reads — takes each
stream from its bigger copy: a local stream from the local file, another
copy's from the remote.

Two processes of one copy may ship the same file: a segment is created only
if it does not exist (``create_log_segment``), and one that does — or a
failed ship, whose upload may have landed — means listing the remote again
and going on from what it holds, exact since both shipped bytes of the same
file.
"""

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.logfiles import next_seq
from vmn_exp.core.status import run_finished
from vmn_exp.core.streams import owned_by
from vmn_exp.storage import ship_state
from vmn_exp.storage.files import (
    is_log_file,
    log_object_name,
    log_sizes_of,
    log_writer_and_seq,
    merged_log,
)

LOCAL, REMOTE = "local", "remote"
_SHIP_ATTEMPTS = 5


def is_any_log(name):
    return is_log_file(name)


def log_writer(name):
    return log_writer_and_seq(name)[0]


def pick_log_sources(remote_sizes, local_sizes):
    """``{stream: LOCAL | REMOTE}``: the copy of each stream's log to read.

    The bigger copy is the newer one; a tie goes to the local copy (no
    download).
    """
    sources = {}
    for writer in set(remote_sizes) | set(local_sizes):
        size = local_sizes.get(writer)
        newest = size is not None and size >= remote_sizes.get(writer, 0)
        sources[writer] = LOCAL if newest else REMOTE
    return sources


def _sizes(files):
    return log_sizes_of((name, sig[0]) for name, sig in files.items())


def _state_of(objects):
    """``(bytes, next seq)`` of a stream's remote log *objects*."""
    return sum(size for _, size in objects), next_seq(objects)


class CachedLogs:
    # Whether local log files are complete copies of their streams' logs
    # (False for a buffer that only holds what this process appended).
    _local_is_replica = True

    def _init_logs(self):
        # (app, verstr, stream) -> LOCAL | REMOTE, as the last listing chose
        self._log_sources = {}
        self._compacted = set()  # streams already compacted after their run finished

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

    # Local only: sync_log_to_remote ships the new bytes periodically. A live
    # run's heartbeat loop (the `exp run` supervisor, the SDK) does that on its
    # own schedule; a one-shot caller with no such loop (`tag`/`add --note`/
    # `create --metrics`) must call sync_log_to_remote itself right after
    # appending -- see core.experiment_writer.flush_log.
    def append_log_entry(self, app_name, verstr, writer_id, entry):
        return self._append_locally(
            self._local.append_log_entry, app_name, verstr, writer_id, entry
        )

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        return self._append_locally(
            self._local.append_log_entries, app_name, verstr, writer_id, entries
        )

    def _append_locally(self, append, app_name, verstr, writer_id, payload):
        if not self._ensure_local_record(app_name, verstr):
            return False
        return append(app_name, verstr, self._owned_stream(app_name, verstr, writer_id), payload)

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
        if not any(local_logs.values()) and not self._local_metrics(app_name, verstr):
            return (
                self._remote.load_merged_log(app_name, verstr) if self._remote else []
            )
        try:
            local_logs = self._with_newer_remote_writers(app_name, verstr, local_logs)
        except Exception:
            VMN_LOGGER.debug(
                "Remote log read failed; showing the local log", exc_info=True
            )
        return merged_log(self, app_name, verstr, local_logs)

    def _local_metrics(self, app_name, verstr):
        return self._local_is_replica and self._local.metric_objects(app_name, verstr)

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

    def _ship_state(self, app_name, verstr, kind):
        """The copy's :class:`~vmn_exp.storage.ship_state.ShipState` of
        *kind*, under its ship lock."""
        record = self._local.local_record_dir(app_name, verstr)
        return ship_state.held(record, kind, repr(self._remote.cache_identity()))

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        """Ship the complete lines appended to each of the copy's own streams
        since the remote's copy ends (*writer_id*'s among them); once the run
        has finished, compact what the remote holds of them. An inherited
        stream (its file came with the copy's directory and never grows) ships
        just what the remote lacks, read from a fresh listing, and is never
        compacted: its owner may have gone on shipping it elsewhere."""
        if not self.remote_for(app_name, verstr):
            return
        owns = self._stream_owned(app_name, verstr)
        inherits = owned_by(self._local.inherited_owners(app_name, verstr))
        local_sizes = {s: n for s, n in self._local.log_sizes(app_name, verstr).items()
                       if owns(s) or inherits(s)}
        if not local_sizes:
            return
        with self._ship_state(app_name, verstr, "log") as state:
            listing = _Listing(self._remote, app_name, verstr)
            for stream, size in sorted(local_sizes.items()):
                held = state if owns(stream) else ship_state.Unknown()
                self._ship_stream(held, listing, app_name, verstr, stream, size)
            if self._run_finished(app_name, verstr):
                for stream in sorted(filter(owns, local_sizes)):
                    self._compact_once(app_name, verstr, stream)

    def _ship_stream(self, state, listing, app_name, verstr, stream, size):
        for _ in range(_SHIP_ATTEMPTS):
            held = state.get(stream) or _state_of(listing.objects(stream))
            offset, seq = held
            chunk = self._complete_lines(app_name, verstr, log_object_name(stream), offset)
            if size <= offset or not chunk:
                state.put(stream, held)
                return
            state.forget(stream)  # until the upload is known to have landed
            if self._ship(app_name, verstr, stream, seq, chunk):
                state.put(stream, (offset + len(chunk), seq + 1))
                return
            listing.refresh()  # another process of the copy shipped it
        raise RuntimeError(f"{verstr}: could not ship the log of {stream!r}")

    def _ship(self, app_name, verstr, stream, seq, chunk):
        """Create segment *seq* of *stream* unless it exists: whether it did."""
        create = getattr(self._remote, "create_log_segment", None)
        if create is None:  # a plugin remote without conditional creates
            self._remote.save_file(app_name, verstr, log_object_name(stream, seq), chunk)
            return True
        return create(app_name, verstr, stream, seq, chunk)

    def _complete_lines(self, app_name, verstr, name, offset):
        """The complete lines of local *name* from *offset* on (b"" if none)."""
        data = self._local.read_file_from(app_name, verstr, name, offset) or b""
        return data[: data.rfind(b"\n") + 1]

    def _run_finished(self, app_name, verstr):
        return run_finished(self._local, app_name, verstr)

    def _compact_once(self, app_name, verstr, stream):
        key = (app_name, verstr, stream)
        if key in self._compacted:
            return
        compact = getattr(self._remote, "compact_log_segments", None)
        if compact is not None:
            try:
                compact(app_name, verstr, stream)
            except Exception:
                # Nothing is lost: the segments stay readable as they are.
                VMN_LOGGER.debug("Log compaction failed", exc_info=True)
                return
        self._compacted.add(key)


class _Listing:
    """One remote listing of a record's log streams, taken when first needed."""

    def __init__(self, remote, app_name, verstr):
        self._remote, self._where, self._groups = remote, (app_name, verstr), None

    def objects(self, stream):
        if self._groups is None:
            self._groups = _groups(self._remote, *self._where)
        return self._groups.get(stream, [])

    def refresh(self):
        self._groups = None


def _groups(remote, app_name, verstr):
    groups = getattr(remote, "log_object_groups", None)
    if groups is not None:
        return groups(app_name, verstr)
    return {w: list(remote.log_objects(app_name, verstr, w))
            for w in remote.log_sizes(app_name, verstr)}
