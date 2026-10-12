#!/usr/bin/env python3
"""Metric streams of the local-disk backend (plan 12 §4.2).

A stream's blocks are appended to ``metrics/<stream>.vms`` with ``O_APPEND``;
before its first append in a process the writer truncates a torn tail (a
block cut short or failing its CRC) so the new block is never hidden behind
it. A block for a stream its record copy retired (it was compacted) goes to
the copy's current stream; one appended while the stream is retired for a
compaction waits for the retirement (:func:`ship_state.append_lock`).
``put_indexed`` moves the finished ``.vmx`` of one of the copy's own streams
in without overwriting one, then drops the stream files it covers.
"""
import os
from contextlib import contextmanager

from vmn_exp.core.metric_block import intact_length
from vmn_exp.core.metric_files import (
    METRICS_DIR,
    group_metric_objects,
    indexed_name,
    is_stream_file,
    stream_name,
    superseded,
)
from vmn_exp.core.streams import owned_by
from vmn_exp.storage import ship_state


def _append(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
    try:
        while data:
            data = data[os.write(fd, data):]
    finally:
        os.close(fd)


def _truncate_torn_tail(path):
    try:
        with open(path, "rb") as f:
            end = intact_length(f)
    except FileNotFoundError:
        return
    if os.path.getsize(path) > end:
        os.truncate(path, end)


def _sizes(folder):
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return {}
    return {f"{METRICS_DIR}/{e.name}": e.stat().st_size
            for e in entries if e.is_file() and not e.name.startswith(".")}


class LocalMetrics:
    def _metrics_dir(self, app_name, verstr, create=False):
        folder = os.path.join(self._snapshot_dir(app_name, verstr), METRICS_DIR)
        if create:
            os.makedirs(folder, exist_ok=True)
        return folder

    def append_metric_block(self, app_name, verstr, writer_id, data):
        if self._refuse_orphan_write(app_name, verstr, "a metric block"):
            return False
        self._metrics_dir(app_name, verstr, create=True)
        record = self._snapshot_dir(app_name, verstr)
        with self.appends_held(app_name, verstr):
            writer_id = self.live_stream(app_name, verstr, writer_id)
            path = os.path.join(record, stream_name(writer_id))
            checked = self.__dict__.setdefault("_checked_streams", set())
            if path not in checked:
                _truncate_torn_tail(path)
                checked.add(path)
            _append(path, data)
        os.utime(record)
        return True

    @contextmanager
    def compacting(self, app_name, verstr, stream):
        """Around a compaction of *stream*: its local file's stream is retired
        first, under the append lock, so a block appended meanwhile is in the
        file the build reads or in the copy's next stream."""
        objects = self.metric_objects(app_name, verstr).get(stream, ())
        if any(is_stream_file(name) for name, _ in objects):
            with self.appends_held(app_name, verstr):
                self.retire_stream(app_name, verstr, stream)
        yield

    def appends_held(self, app_name, verstr):
        """No metric block is appended to the record meanwhile."""
        return ship_state.append_lock(self._snapshot_dir(app_name, verstr))

    def metric_objects(self, app_name, verstr):
        return group_metric_objects(_sizes(self._metrics_dir(app_name, verstr)))

    def read_range(self, app_name, verstr, name, offset, length):
        path = os.path.join(self._snapshot_dir(app_name, verstr), name)
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                return f.read(length)
        except FileNotFoundError:
            return None

    def put_indexed(self, app_name, verstr, writer_id, path, replace=False, covers=0):
        """Move *path* in as the stream's ``.vmx`` covering its segments up
        to *covers*; False if that one is there and not *replace*, or if the
        stream is not the copy's own (one it inherited is a stale prefix of
        what its owner may have gone on appending elsewhere)."""
        if self._refuse_orphan_write(app_name, verstr, "a metric index"):
            return False
        if not owned_by(self.stream_owners(app_name, verstr))(writer_id):
            return False
        record = self._snapshot_dir(app_name, verstr)
        self._metrics_dir(app_name, verstr, create=True)
        if not _move_in(path, os.path.join(record, indexed_name(writer_id, covers)), replace):
            return False
        names = _sizes(os.path.join(record, METRICS_DIR))
        for name in superseded(names, writer_id, covers):
            os.unlink(os.path.join(record, name))
        os.utime(record)
        return True


def _move_in(path, dest, replace):
    if replace:
        os.replace(path, dest)
        return True
    try:
        os.link(path, dest)
    except FileExistsError:
        return False
    except OSError:
        if os.path.exists(dest):
            return False
        os.replace(path, dest)  # no hard links here (another filesystem)
    else:
        os.unlink(path)
    return True
