#!/usr/bin/env python3
"""Metric streams on S3 and the S3-shaped object stores (plan 12 §4.2).

Objects have no append, so a writer's stream is its segments
``metrics/<w>[@<seq>].vms``, each created under ``If-None-Match`` (two
processes sharing a writer id take the next free seq instead of overwriting).
``read_range`` is a ranged GET. ``put_indexed`` creates the writer's ``.vmx``
conditionally and only then deletes the stream objects it supersedes, as
:meth:`S3Logs.compact_log_segments` does.
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.metric_files import (
    METRICS_DIR,
    group_metric_objects,
    indexed_name,
    is_part_file,
    is_stream_file,
    metric_writer,
    part_name,
    stream_name,
    stream_writer_and_seq,
)
from vmn_exp.storage.s3_base import error_code, is_missing, is_taken


class S3Metrics:
    def _metric_sizes(self, app_name, verstr):
        prefix = f"{self._record_prefix(app_name, verstr)}/"
        return {o["Key"][len(prefix):]: o["Size"]
                for o in self._objects(f"{prefix}{METRICS_DIR}/")}

    def metric_objects(self, app_name, verstr):
        return group_metric_objects(self._metric_sizes(app_name, verstr))

    def put_metric_segment(self, app_name, verstr, writer_id, seq, data):
        """Store *data* as the writer's segment *seq* or the next free one."""
        prefix = self._record_prefix(app_name, verstr)
        return self._put_next_free(
            lambda n: f"{prefix}/{stream_name(writer_id, n)}", seq, data)

    def append_metric_block(self, app_name, verstr, writer_id, data):
        """Append as the writer's next segment (direct remote writes)."""
        if not self.exists(app_name, verstr):
            return False
        names = self._metric_sizes(app_name, verstr)
        seqs = [stream_writer_and_seq(n)[1] for n in names
                if is_stream_file(n) and stream_writer_and_seq(n)[0] == writer_id]
        self.put_metric_segment(app_name, verstr, writer_id,
                                max(seqs) + 1 if seqs else 0, data)
        return True

    def read_range(self, app_name, verstr, name, offset, length):
        if length <= 0:
            return b""
        key = f"{self._record_prefix(app_name, verstr)}/{name}"
        try:
            resp = self._s3.get_object(
                Bucket=self.bucket, Key=key,
                Range=f"bytes={offset}-{offset + length - 1}")
            return resp["Body"].read()
        except Exception as e:
            if error_code(e) in ("416", "InvalidRange"):
                return b""
            if not is_missing(e):
                VMN_LOGGER.debug(f"Error reading {key}", exc_info=True)
            return None

    def put_indexed(self, app_name, verstr, writer_id, path, part=None, replace=False):
        """Upload *path* as the writer's ``.vmx`` (or sealed *part*); False
        if one is there and not *replace*."""
        prefix = self._record_prefix(app_name, verstr)
        name = indexed_name(writer_id) if part is None else part_name(writer_id, part)
        with open(path, "rb") as f:
            data = f.read()
        try:
            self._put(f"{prefix}/{name}", data, **({} if replace else {"IfNoneMatch": "*"}))
        except Exception as e:
            if is_taken(e):
                return False
            raise
        superseded = [n for n in self._metric_sizes(app_name, verstr)
                      if (is_stream_file(n) or (part is None and is_part_file(n)))
                      and metric_writer(n) == writer_id]
        self._delete_keys([f"{prefix}/{n}" for n in superseded])
        return True
