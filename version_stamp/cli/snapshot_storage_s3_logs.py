#!/usr/bin/env python3
"""S3 experiment logs: per-writer objects, segments, and their compaction.

A writer's log is ``log.<w>.jsonl`` plus segments ``log.<w>@<seq>.jsonl``: a
local-first host ships each sync's new lines as a new segment (re-uploading a
growing log every sync is quadratic). :meth:`compact_log_segments` merges a
finished writer's objects into one, so reading a finished run costs one GET;
the merged object supersedes what it covers (``group_log_names``), so readers
listing it next to not-yet-deleted segments never count an entry twice.
"""

import json

from version_stamp.cli.snapshot_storage_files import (
    LEGACY_LOG_FILE,
    flatten_logs,
    group_log_names,
    log_object_name,
    log_sizes_of,
    log_writer_and_seq,
    parse_jsonl,
)
from version_stamp.cli.snapshot_storage_s3_base import is_taken, parallel_map
from version_stamp.core import utils as core_utils
from version_stamp.core.experiment_logfiles import compacted_log_name
from version_stamp.core.logging import VMN_LOGGER

_APPEND_ATTEMPTS = 20


def _wanted(writer, writers):
    return writers is None or writer in writers


class S3Logs:
    def _log_names(self, prefix):
        """The log object names (``log.yml`` included) under record *prefix*/."""
        return {
            o["Key"][len(prefix) :]: o["Size"] for o in self._objects(prefix + "log")
        }

    def log_objects(self, app_name, verstr, writer_id):
        """``[(name, size)]`` of the writer's visible log objects, in order."""
        sizes = self._log_names(f"{self._record_prefix(app_name, verstr)}/")
        return [(n, sizes[n]) for n in group_log_names(sizes).get(writer_id, [])]

    def delete_log_segments(self, app_name, verstr, writer_id):
        prefix = self._record_prefix(app_name, verstr)
        self._delete_keys(
            [
                f"{prefix}/{name}"
                for name, _ in self.log_objects(app_name, verstr, writer_id)
                if log_writer_and_seq(name)[1]
            ]
        )

    def put_log_segment(self, app_name, verstr, writer_id, seq, data):
        """Store *data* as the writer's segment *seq* — or the next free one,
        so two processes sharing a writer id never overwrite each other.
        Returns the seq used."""
        prefix = self._record_prefix(app_name, verstr)
        for _ in range(_APPEND_ATTEMPTS):
            try:
                key = f"{prefix}/{log_object_name(writer_id, seq)}"
                self._put(key, data, IfNoneMatch="*")
                return seq
            except Exception as e:
                if not is_taken(e):
                    raise
                seq += 1
        raise RuntimeError(f"Could not store a log segment of {writer_id}")

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        """Append to this writer's single log object.

        S3 has no append, so this reads and rewrites the object — under an
        ETag precondition, so an entry another process appended in between
        makes this write retry instead of silently overwriting it. A writer
        whose log is already segmented (or compacted) gets a new segment
        instead: a rewritten base would sit behind them unread.
        """
        line = (json.dumps(entry, default=str) + "\n").encode("utf-8")
        objects = self.log_objects(app_name, verstr, writer_id)
        if objects and objects[-1][0] != log_object_name(writer_id):
            seq = log_writer_and_seq(objects[-1][0])[1] + 1
            self.put_log_segment(app_name, verstr, writer_id, seq, line)
            return True
        key = f"{self._record_prefix(app_name, verstr)}/{log_object_name(writer_id)}"
        for _ in range(_APPEND_ATTEMPTS):
            body, etag = self._get_with_etag(key)
            condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
            try:
                self._put(key, (body or b"") + line, **condition)
                return True
            except Exception as e:
                if not is_taken(e):
                    raise
        raise RuntimeError(f"Could not append to {key}: too many concurrent writers")

    def log_sizes(self, app_name, verstr):
        prefix = f"{self._record_prefix(app_name, verstr)}/"
        return log_sizes_of(self._log_names(prefix).items())

    def load_logs_by_writer(self, app_name, verstr, writers=None):
        """``{writer: entries}``; only *writers* (``""`` = log.yml) when given.

        Objects are fetched concurrently; a failed fetch raises rather than
        passing for an empty object.
        """
        prefix = f"{self._record_prefix(app_name, verstr)}/"
        names = self._log_names(prefix)
        groups = {
            w: group
            for w, group in group_log_names(names).items()
            if _wanted(w, writers)
        }
        fetch = [n for group in groups.values() for n in group]
        if LEGACY_LOG_FILE in names and _wanted("", writers):
            fetch.append(LEGACY_LOG_FILE)
        bodies = dict(
            zip(fetch, parallel_map(self._get_or_raise, [prefix + n for n in fetch]))
        )
        logs = {}
        legacy = bodies.get(LEGACY_LOG_FILE)
        if legacy:
            loaded = core_utils.yaml_safe_load(legacy)
            if isinstance(loaded, list):
                logs[""] = loaded
        for writer, group in groups.items():
            entries = logs.setdefault(writer, [])
            for name in group:
                if bodies[name]:
                    entries.extend(parse_jsonl(bodies[name].decode("utf-8"), writer))
        return logs

    def load_merged_log(self, app_name, verstr):
        try:
            return flatten_logs(self.load_logs_by_writer(app_name, verstr))
        except Exception:
            VMN_LOGGER.debug("Failed to load S3 experiment log", exc_info=True)
            return []

    def compact_log_segments(self, app_name, verstr, writer_id):
        """Merge the writer's log objects into one; True if anything was merged.

        The merged object is byte-for-byte their concatenation, so sizes (and
        with them a syncing host's offsets) are unchanged. It is written under
        ``If-None-Match`` — a second compactor of the same objects backs off —
        and only then are the merged objects deleted. Call it once the writer
        is done: an append racing the merge could otherwise be deleted with it.
        """
        objects = self.log_objects(app_name, verstr, writer_id)
        if len(objects) < 2:
            return False
        prefix = self._record_prefix(app_name, verstr)
        keys = [f"{prefix}/{name}" for name, _ in objects]
        bodies = parallel_map(self._get_or_raise, keys)
        if any(body is None for body in bodies):
            return False  # changed under us: leave it to the next attempt
        last_seq = log_writer_and_seq(objects[-1][0])[1]
        merged = f"{prefix}/{compacted_log_name(writer_id, last_seq)}"
        try:
            self._put(merged, b"".join(bodies), IfNoneMatch="*")
        except Exception as e:
            if is_taken(e):
                return False
            raise
        self._delete_keys(keys)
        return True
