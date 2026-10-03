#!/usr/bin/env python3
"""The metric-stream half of local-first storage (plan 12 §4.2).

Blocks are appended to the local ``metrics/<w>.vms``;
:meth:`CachedMetrics.sync_metrics_to_remote` ships the intact blocks appended
since the last sync as the next segment ``metrics/<w>@<seq>.vms``, as
:mod:`cached_logs` ships log lines. Each writer is read from one copy: an
indexed ``.vmx`` wherever it is, else the bigger stream (ties stay local);
:meth:`read_range` reads the copy the last listing picked, since the local
stream and the remote base segment share a name.
"""
from vmn_exp.core.metric_block import intact_length
from vmn_exp.core.metric_files import (
    is_indexed_file,
    is_stream_file,
    metric_writer,
    stream_name,
    stream_writer_and_seq,
)

LOCAL, REMOTE = "local", "remote"


def _pick(local, remote):
    """LOCAL or REMOTE for one writer's ``[(name, size)]`` copies."""
    if any(is_indexed_file(n) for n, _ in remote):
        return REMOTE
    if any(is_indexed_file(n) for n, _ in local) or not remote:
        return LOCAL
    return LOCAL if sum(s for _, s in local) >= sum(s for _, s in remote) else REMOTE


class CachedMetrics:
    def _metric_state(self):
        # (app, verstr, writer) -> source picked / (remote bytes, next seq)
        return self.__dict__.setdefault("_metrics", {"sources": {}, "synced": {}})

    def append_metric_block(self, app_name, verstr, writer_id, data):
        if not self._ensure_local_record(app_name, verstr):
            return False
        return self._local.append_metric_block(app_name, verstr, writer_id, data)

    def metric_objects(self, app_name, verstr):
        local = self._local.metric_objects(app_name, verstr) if self._local_is_replica else {}
        remote = self._remote.metric_objects(app_name, verstr) if self._remote else {}
        sources, picked = self._metric_state()["sources"], {}
        for writer in set(local) | set(remote):
            source = _pick(local.get(writer, []), remote.get(writer, []))
            sources[(app_name, verstr, writer)] = source
            picked[writer] = (local if source == LOCAL else remote)[writer]
        return picked

    def read_range(self, app_name, verstr, name, offset, length):
        writer = metric_writer(name)
        default = LOCAL if self._local_is_replica else REMOTE
        source = self._metric_state()["sources"].get((app_name, verstr, writer), default)
        if source == REMOTE and self._remote:
            return self._remote.read_range(app_name, verstr, name, offset, length)
        data = self._local.read_range(app_name, verstr, name, offset, length)
        if data is None and self._remote:
            return self._remote.read_range(app_name, verstr, name, offset, length)
        return data

    def put_indexed(self, app_name, verstr, writer_id, path, part=None, replace=False):
        """The ``.vmx`` goes to the remote (when it holds the record) and the
        local copy; the local one takes *path*."""
        if not self._ensure_local_record(app_name, verstr):
            return False
        stored = True
        remote = self.remote_for(app_name, verstr)
        if remote:
            stored = remote.put_indexed(app_name, verstr, writer_id, path, part, replace)
        self._metric_state()["synced"].pop((app_name, verstr, writer_id), None)
        return self._local.put_indexed(app_name, verstr, writer_id, path, part, replace) and stored

    def sync_metrics_to_remote(self, app_name, verstr, writer_id):
        """Ship the writer's intact blocks appended since the last sync."""
        remote = self.remote_for(app_name, verstr)
        if not remote:
            return
        with self._sync_lock:
            self._ship_new_blocks(remote, app_name, verstr, writer_id)

    def _ship_new_blocks(self, remote, app_name, verstr, writer_id):
        synced = self._metric_state()["synced"]
        key = (app_name, verstr, writer_id)
        if key not in synced:
            synced[key] = self._initial_metric_state(remote, app_name, verstr, writer_id)
        if synced[key] is None:
            return  # the remote already holds the writer's .vmx
        offset, seq = synced[key]
        name = stream_name(writer_id)
        data = self._local.read_file_from(app_name, verstr, name, offset) or b""
        chunk = data[: intact_length(data)]
        if chunk:
            used = remote.put_metric_segment(app_name, verstr, writer_id, seq, chunk)
            synced[key] = (offset + len(chunk), used + 1)

    def _initial_metric_state(self, remote, app_name, verstr, writer_id):
        """``(bytes the remote holds, next seq)``, None once it is indexed."""
        objects = remote.metric_objects(app_name, verstr).get(writer_id, [])
        if any(is_indexed_file(n) for n, _ in objects):
            return None
        streams = [(n, size) for n, size in objects if is_stream_file(n)]
        seqs = [stream_writer_and_seq(n)[1] for n, _ in streams]
        offset = sum(size for _, size in streams) if self._local_is_replica else 0
        return offset, (max(seqs) + 1 if seqs else 0)
