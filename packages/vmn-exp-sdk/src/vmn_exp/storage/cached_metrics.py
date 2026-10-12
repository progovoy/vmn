#!/usr/bin/env python3
"""The metric-stream half of local-first storage (plan 12 §4.2).

Blocks are appended to the local ``metrics/<stream>.vms`` of the record copy
that owns the stream; :meth:`CachedMetrics.sync_metrics_to_remote` ships the
intact blocks past what the remote holds of each of the copy's streams as
the next segment ``metrics/<stream>@<seq>.vms``, created only if it does not
exist, as :mod:`cached_logs` ships log lines (:mod:`ship_state` remembers
what the remote holds, for every process of the copy).

Each stream is read from one copy: the local file of its owner (a superset of
what it shipped, also when another copy compacted the stream on the remote),
else the remote's — or a local ``.vmx`` when the remote has none. A copy owns
the streams of its current and retired owners (:mod:`stream_owner`); the
others' local files (a ``cp -r`` of the original's root) are stale prefixes:
read and compacted from the remote, never shipped (the owner's ship state
assumes it alone ships its stream) nor put as a ``.vmx``.
:meth:`read_range` reads the copy the last listing picked, since the local
stream and the remote base segment share a name.

Compacting a stream the copy owns (its end of run, a seal, ``vmn-exp
compact`` in the same copy) builds the ``.vmx`` from the local file under the
copy's ship lock, covering every segment the remote holds then, and retires
the stream first (:mod:`local_streams`): blocks appended meanwhile go to the
copy's next stream. A stream another copy compacted while this one still had
blocks to ship is compacted again from the local file at its next ship.
"""
import os
from contextlib import contextmanager

from vmn_exp.core.metric_block import intact_length
from vmn_exp.core.metric_files import (
    covered_seq,
    is_indexed_file,
    is_stream_file,
    last_seq,
    metric_writer,
    stream_name,
)
from vmn_exp.core.streams import display_writer, owner_of, stream_key
from vmn_exp.storage import ship_state

LOCAL, REMOTE = "local", "remote"
_SHIP_ATTEMPTS = 5
_INDEXED = (-1, -1)  # ship state: the remote holds the stream's local .vmx


def _has_stream(objects):
    return any(is_stream_file(n) for n, _ in objects)


def _pick(local, remote, owned):
    """LOCAL or REMOTE for one stream's ``[(name, size)]`` copies."""
    if not remote or (owned and _has_stream(local)):
        return LOCAL  # the owner's file holds all the stream ever shipped
    if not owned or not local or any(is_indexed_file(n) for n, _ in remote):
        return REMOTE  # another copy's file here is a stale prefix of it
    return LOCAL


def _remote_state(objects):
    """``(bytes, next seq)`` the remote holds of a stream that it has not
    compacted (*objects*: its segments), else None."""
    if any(is_indexed_file(n) for n, _ in objects):
        return None
    return sum(size for _, size in objects), last_seq(n for n, _ in objects) + 1


class CachedMetrics:
    def _metric_state(self):
        # (app, verstr, stream) -> the copy last picked
        return self.__dict__.setdefault("_metrics", {"sources": {}})

    def append_metric_block(self, app_name, verstr, writer_id, data):
        """Append to the local copy's stream: one named for an owner the copy
        does not own (a one-off one, named while the record could not be
        fetched) is the copy's own stream of its writer."""
        if not self._ensure_local_record(app_name, verstr):
            return False
        if not self._stream_owned(app_name, verstr)(writer_id):
            writer = display_writer(writer_id)
            writer_id = stream_key(writer, self._local.stream_owner(app_name, verstr, writer))
        return self._local.append_metric_block(app_name, verstr, writer_id, data)

    def metric_objects(self, app_name, verstr):
        local = self._local.metric_objects(app_name, verstr) if self._local_is_replica else {}
        remote = self._remote.metric_objects(app_name, verstr) if self._remote else {}
        sources, picked = self._metric_state()["sources"], {}
        owns = self._stream_owned(app_name, verstr)
        for writer in set(local) | set(remote):
            source = _pick(local.get(writer, []), remote.get(writer, []), owns(writer))
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

    @contextmanager
    def compacting(self, app_name, verstr, stream):
        """Around a compaction of *stream*: one the copy owns (its local file
        is there) is retired and built under the copy's ship lock."""
        local = self._local.metric_objects(app_name, verstr).get(stream, [])
        record = self._local.local_record_dir(app_name, verstr)
        if not (_has_stream(local) and record and self._stream_owned(app_name, verstr)(stream)):
            yield
            return
        with ship_state.ship_lock(record):
            self.retire_stream(app_name, verstr, stream)
            yield

    def put_indexed(self, app_name, verstr, writer_id, path, replace=False, covers=0):
        """A ``.vmx`` built from the copy's own file (a superset of what any
        copy shipped of the stream) covers every segment the remote holds now
        (the build ran under the ship lock) and replaces whatever ``.vmx``
        the remote has; it goes to the remote, then here. One built from the
        remote's objects goes to the remote only."""
        if not self._ensure_local_record(app_name, verstr):
            return False
        remote = self.remote_for(app_name, verstr)
        source = self._metric_state()["sources"].get((app_name, verstr, writer_id), LOCAL)
        if source == REMOTE:
            return bool(remote) and remote.put_indexed(
                app_name, verstr, writer_id, path, replace, covers)
        if remote and not self._stream_owned(app_name, verstr)(writer_id):
            return False  # built from another copy's stale file
        if remote:
            with self._ship_state(app_name, verstr, "metrics") as state:
                names = [n for n, _ in remote.metric_objects(app_name, verstr).get(writer_id, [])]
                covers = max(covers, last_seq(names))
                state.forget(writer_id)  # until the .vmx is known to be up
                remote.put_indexed(app_name, verstr, writer_id, path, True, covers)
                state.put(writer_id, _INDEXED)
        return self._local.put_indexed(app_name, verstr, writer_id, path, True, covers)

    def _stream_owned(self, app_name, verstr):
        """Whether a local stream is the copy's own: one of its current or
        retired owner's (or a plain name, which has no other owner), not one
        copied along with another root."""
        owners = self._local.stream_owners(app_name, verstr)
        return lambda stream: not owner_of(stream) or owner_of(stream) in owners

    def sync_metrics_to_remote(self, app_name, verstr, writer_id):
        """Ship the intact blocks appended to each of the copy's streams past
        what the remote holds (*writer_id*'s among them)."""
        remote = self.remote_for(app_name, verstr)
        if not remote:
            return
        local = self._local.metric_objects(app_name, verstr)
        if not local:
            return
        with self._ship_state(app_name, verstr, "metrics") as state:
            listing = _Listing(remote, app_name, verstr)
            owns = self._stream_owned(app_name, verstr)
            for stream, objects in sorted(local.items()):
                if not owns(stream):
                    continue
                if _has_stream(objects):
                    self._ship_blocks(state, listing, remote, app_name, verstr, stream)
                else:
                    self._ship_indexed(state, listing, remote, app_name, verstr, stream, objects)

    def _ship_indexed(self, state, listing, remote, app_name, verstr, stream, objects):
        """A ``.vmx`` the copy built while the remote was out of reach goes up
        (over any the remote has: the copy's own file held all it shipped)."""
        (name, _), = objects
        if state.get(stream) == _INDEXED:
            return
        theirs = [n for n, _ in listing.objects(stream)]
        path = os.path.join(self._local.local_record_dir(app_name, verstr), name)
        covers = max(covered_seq(name), last_seq(theirs))
        remote.put_indexed(app_name, verstr, stream, path, replace=True, covers=covers)
        state.put(stream, _INDEXED)

    def _ship_blocks(self, state, listing, remote, app_name, verstr, stream):
        for _ in range(_SHIP_ATTEMPTS):
            held = state.get(stream)
            if held in (None, _INDEXED):
                held = _remote_state(listing.objects(stream))
            if held is None:  # another copy compacted it: compact it again
                self._recompact(app_name, verstr, stream)
                state.forget(stream)
                return
            offset, seq = held
            data = self._local.read_file_from(app_name, verstr, stream_name(stream), offset) or b""
            chunk = data[: intact_length(data)]
            if not chunk:
                state.put(stream, held)
                return
            state.forget(stream)  # until the upload is known to have landed
            if remote.create_metric_segment(app_name, verstr, stream, seq, chunk):
                state.put(stream, (offset + len(chunk), seq + 1))
                return
            listing.refresh()  # another process of the copy shipped it
        raise RuntimeError(f"{verstr}: could not ship the metrics of {stream!r}")

    def _recompact(self, app_name, verstr, stream):
        from vmn_exp.core.metric_compact import compact_writer, record_rewinds

        compact_writer(self, app_name, verstr, stream,
                       record_rewinds(self, app_name, verstr), rebuild=True)


class _Listing:
    """One remote listing of a record's metric streams, taken when first needed."""

    def __init__(self, remote, app_name, verstr):
        self._remote, self._where, self._groups = remote, (app_name, verstr), None

    def objects(self, stream):
        if self._groups is None:
            self._groups = self._remote.metric_objects(*self._where)
        return self._groups.get(stream, [])

    def refresh(self):
        self._groups = None
