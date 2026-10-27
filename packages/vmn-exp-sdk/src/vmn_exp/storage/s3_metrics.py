#!/usr/bin/env python3
"""Metric streams on S3 and the S3-shaped object stores (plan 12 §4.2).

Objects have no append, so a stream is its segments
``metrics/<stream>[@<seq>].vms``, each created under ``If-None-Match``
(:meth:`create_metric_segment`: a stream's segments are never overwritten).
``read_range`` is a ranged GET. ``put_indexed`` creates the stream's ``.vmx``
conditionally and only then deletes the segments up to the seq it covers,
as :meth:`S3Logs.compact_log_segments` does.
"""
from vmn_exp.core.metric_files import (
    METRICS_DIR,
    group_metric_objects,
    indexed_name,
    is_stream_file,
    stream_name,
    stream_writer_and_seq,
    superseded,
)
from vmn_exp.storage.s3_base import error_code, is_missing


class S3Metrics:
    def _metric_sizes(self, app_name, verstr):
        prefix = f"{self._record_prefix(app_name, verstr)}/"
        return {o["Key"][len(prefix):]: o["Size"]
                for o in self._objects(f"{prefix}{METRICS_DIR}/")}

    def metric_objects(self, app_name, verstr):
        return group_metric_objects(self._metric_sizes(app_name, verstr))

    def metric_objects_listed(self, sigs):
        """:meth:`metric_objects` as a listing found them: *sigs*
        ``{name: (size, mtime, etag)}`` (:meth:`list_files`)."""
        return group_metric_objects({name: sig[0] for name, sig in sigs.items()})

    def create_metric_segment(self, app_name, verstr, stream, seq, data):
        """Store *data* as the stream's segment *seq* unless that exists:
        whether it was created."""
        prefix = self._record_prefix(app_name, verstr)
        return self._create(f"{prefix}/{stream_name(stream, seq)}", data)

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
        """*length* bytes of *name* from *offset*; None when it is missing. A
        failed read raises: taken for a missing object, it would leave points
        out of a compaction that then deletes them."""
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
            if is_missing(e):
                return None
            raise

    def put_indexed(self, app_name, verstr, writer_id, path, replace=False, covers=0):
        """Upload *path* as the stream's ``.vmx`` covering its segments up to
        *covers*; False if that one is there and not *replace*. Then the
        objects it covers are deleted — none shipped since the build read
        the stream (their seqs are past *covers*)."""
        prefix = self._record_prefix(app_name, verstr)
        with open(path, "rb") as f:
            data = f.read()
        key = f"{prefix}/{indexed_name(writer_id, covers)}"
        if replace:
            self._put(key, data)
        elif not self._create(key, data):
            return False
        names = superseded(self._metric_sizes(app_name, verstr), writer_id, covers)
        self._delete_keys([f"{prefix}/{n}" for n in names])
        return True
