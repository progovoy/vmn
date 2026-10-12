"""Inherited streams: noting what the remote lacks of them, and adopting them.

A record copy inherits the streams of the directory it was copied, restored
or moved from (:mod:`vmn_exp.storage.stream_owner`); only their owner ships
them, so a sync or a push notes, once, when the remote lacks some of them.
:func:`adopt_streams` (``vmn-exp push --adopt``) makes this copy their owner:
for when the original checkout is gone or will never write again. Their
local files first catch up with what the remote holds of them (the original
may have shipped more after the copy was made; a stream it compacted on the
remote leaves the copy's stale files), so from then on they are the copy's
own — a superset of their remote copy — and are shipped, sealed, compacted
and pushed as such.
"""
import os

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.metric_block import intact_length
from vmn_exp.core.metric_files import (
    is_indexed_file,
    is_stream_file,
    stream_writer_and_seq,
)
from vmn_exp.core.streams import owner_of
from vmn_exp.storage import ship_state, stream_owner
from vmn_exp.storage.files import atomic_write, log_object_name

_NOTED = set()


def _theirs(local, app_name, verstr):
    owners = local.inherited_owners(app_name, verstr)
    return lambda stream: owner_of(stream) in owners


def _remote_bytes(objects):
    return sum(size for _, size in objects)


def _lacks_metrics(objects, theirs):
    if any(is_indexed_file(n) for n, _ in theirs):
        return False
    if any(is_stream_file(n) for n, _ in objects):
        return _remote_bytes(objects) > _remote_bytes(theirs)
    return bool(objects)


def missing_inherited(local, remote, app_name, verstr):
    """The streams *local*'s copy inherited whose remote copy lacks some of
    the local bytes, sorted. No remote call without inherited streams."""
    theirs = _theirs(local, app_name, verstr)
    logs = {s: n for s, n in local.log_sizes(app_name, verstr).items() if theirs(s)}
    metrics = {s: o for s, o in local.metric_objects(app_name, verstr).items() if theirs(s)}
    missing = set()
    if logs:
        remote_sizes = remote.log_sizes(app_name, verstr)
        missing |= {s for s, n in logs.items() if n > remote_sizes.get(s, 0)}
    if metrics:
        remote_objects = remote.metric_objects(app_name, verstr)
        missing |= {s for s, o in metrics.items() if _lacks_metrics(o, remote_objects.get(s, []))}
    return sorted(missing)


def inherited_note(app_name, verstr, streams):
    return (f"{len(streams)} stream(s) of this record came from another checkout "
            f"({', '.join(streams)}) and the remote lacks part of them; only their owner "
            f"pushes them. If that checkout is gone for good, run "
            f"`vmn-exp push {app_name} -v {verstr} --adopt`")


def note_missing_inherited(local, remote, app_name, verstr):
    """Warn once per process about what the remote lacks of the copy's
    inherited streams (advice only: a failed listing is not reported)."""
    try:
        streams = missing_inherited(local, remote, app_name, verstr)
    except Exception:
        VMN_LOGGER.debug("Listing inherited streams failed", exc_info=True)
        return
    key = (app_name, verstr, tuple(streams))
    if streams and key not in _NOTED:
        _NOTED.add(key)
        VMN_LOGGER.warning(f"{verstr}: {inherited_note(app_name, verstr, streams)}")


def adopt_streams(local, remote, app_name, verstr):
    """Make *local*'s copy of the record the owner of the streams it
    inherited, after catching their files up with *remote*'s copies; the
    owners adopted, sorted."""
    record = local.local_record_dir(app_name, verstr)
    if record is None or not local.inherited_owners(app_name, verstr):
        return []
    theirs = _theirs(local, app_name, verstr)
    with ship_state.ship_lock(record):
        _catch_up_logs(local, remote, app_name, verstr, record, theirs)
        _catch_up_metrics(local, remote, app_name, verstr, record, theirs)
        ship_state.forget_streams(record, theirs)
        return stream_owner.adopt(record)


def _replace(record, name, local, remote):
    """Write *remote* bytes as local file *name* when they extend *local*'s
    complete part; refuse when they do not."""
    if len(remote) <= len(local):
        return
    if not remote.startswith(local):
        raise ValueError(f"{name}: the remote copy is not an extension of the local one; "
                         "not adopting it")
    atomic_write(os.path.join(record, name), remote)


def _catch_up_logs(local, remote, app_name, verstr, record, theirs):
    sizes = remote.log_sizes(app_name, verstr)
    for stream, size in local.log_sizes(app_name, verstr).items():
        if not theirs(stream) or sizes.get(stream, 0) <= size:
            continue
        name = log_object_name(stream)
        mine = local.read_file_from(app_name, verstr, name, 0) or b""
        _replace(record, name, mine[: mine.rfind(b"\n") + 1],
                 b"".join(_read(remote.load_file(app_name, verstr, n), n)
                          for n, _ in remote.log_objects(app_name, verstr, stream)))


def _catch_up_metrics(local, remote, app_name, verstr, record, theirs):
    remote_objects = remote.metric_objects(app_name, verstr)
    for stream, objects in local.metric_objects(app_name, verstr).items():
        if not theirs(stream):
            continue
        held = remote_objects.get(stream, [])
        if any(is_indexed_file(n) for n, _ in held):
            # its owner compacted all it had: the copy's files are a prefix
            for name, _ in objects:
                os.unlink(os.path.join(record, name))
            continue
        base = [n for n, _ in objects if is_stream_file(n)]
        if base and _remote_bytes(held) > _remote_bytes(objects):
            mine = local.read_range(app_name, verstr, base[0], 0, _remote_bytes(objects)) or b""
            ordered = sorted(held, key=lambda o: stream_writer_and_seq(o[0])[1])
            _replace(record, base[0], mine[: intact_length(mine)], b"".join(
                _read(remote.read_range(app_name, verstr, n, 0, size), n) for n, size in ordered))


def _read(data, name):
    if data is None:
        raise RuntimeError(f"{name}: the remote read failed; not adopting")
    return data
