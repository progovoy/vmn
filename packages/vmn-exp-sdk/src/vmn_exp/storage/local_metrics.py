#!/usr/bin/env python3
"""Metric streams of the local-disk backend (plan 12 §4.2).

A writer appends blocks to ``metrics/<writer>.vms`` with ``O_APPEND``; before
its first append in a process it truncates a torn tail (a block cut short or
failing its CRC) so the new block is never hidden behind it. ``put_indexed``
moves the finished ``.vmx`` in without overwriting one, then drops the
writer's stream files.
"""
import os

from vmn_exp.core.metric_block import intact_length
from vmn_exp.core.metric_files import (
    METRICS_DIR,
    group_metric_objects,
    indexed_name,
    is_part_file,
    is_stream_file,
    metric_writer,
    part_name,
    stream_name,
)


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
        path = os.path.join(self._snapshot_dir(app_name, verstr), stream_name(writer_id))
        checked = self.__dict__.setdefault("_checked_streams", set())
        if path not in checked:
            _truncate_torn_tail(path)
            checked.add(path)
        _append(path, data)
        os.utime(self._snapshot_dir(app_name, verstr))
        return True

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

    def put_indexed(self, app_name, verstr, writer_id, path, part=None, replace=False):
        """Move *path* in as the writer's ``.vmx`` (or sealed *part*); False
        if one is there and not *replace*."""
        if self._refuse_orphan_write(app_name, verstr, "a metric index"):
            return False
        record = self._snapshot_dir(app_name, verstr)
        self._metrics_dir(app_name, verstr, create=True)
        name = indexed_name(writer_id) if part is None else part_name(writer_id, part)
        if not _move_in(path, os.path.join(record, name), replace):
            return False
        self._drop_streams(record, writer_id, parts=part is None)
        os.utime(record)
        return True

    def drop_indexed(self, app_name, verstr, writer_id):
        record = self._snapshot_dir(app_name, verstr)
        try:
            os.unlink(os.path.join(record, indexed_name(writer_id)))
        except FileNotFoundError:
            return
        os.utime(record)

    def _drop_streams(self, record, writer_id, parts):
        sizes = _sizes(os.path.join(record, METRICS_DIR))
        for name in sizes:
            dropped = is_stream_file(name) or (parts and is_part_file(name))
            if dropped and metric_writer(name) == writer_id:
                os.unlink(os.path.join(record, name))


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
