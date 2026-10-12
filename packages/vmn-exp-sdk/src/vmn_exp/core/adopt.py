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
and pushed as such. A remote ``.vmx`` need not hold all the copy has (another
clone's ``vmn-exp compact`` builds it from what the original shipped): the
copy's files of its stream go only when the ``.vmx`` holds at least as many
points (both are prefixes of the one owner's stream), else adopt refuses the
run and changes nothing.
"""
import os

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.metric_block import intact_length, read_headers
from vmn_exp.core.metric_files import (
    covered_seq,
    is_indexed_file,
    is_stream_file,
    stream_writer_and_seq,
)
from vmn_exp.core.metric_index_reader import MetricIndexReader
from vmn_exp.core.streams import owner_of
from vmn_exp.storage import ship_state, stream_owner
from vmn_exp.storage.files import atomic_write, log_object_name

_LISTED = set()


def _theirs(local, app_name, verstr):
    owners = local.inherited_owners(app_name, verstr)
    return lambda stream: owner_of(stream) in owners


def _remote_bytes(objects):
    return sum(size for _, size in objects)


def _reader(storage, app_name, verstr, name):
    return lambda offset, length: _read(
        storage.read_range(app_name, verstr, name, offset, length), name)


def _footer(storage, app_name, verstr, name, size):
    return MetricIndexReader(_reader(storage, app_name, verstr, name), size).footer


def _points(storage, app_name, verstr, objects, local=True, past=-1):
    """Points held by *objects*: footers of ``.vmx`` files plus block headers
    of streams (remote ones only past segment *past*, which a ``.vmx`` holds);
    a failed read raises. A local ``.vmx`` with rewinds applied counts as
    infinite: its points need not be a prefix."""
    total = 0
    for name, size in objects:
        if is_indexed_file(name):
            footer = _footer(storage, app_name, verstr, name, size)
            if local and footer.get("rewinds_applied"):
                return float("inf")
            total += footer["rows"]
        elif is_stream_file(name) and (local or stream_writer_and_seq(name)[1] > past):
            data = _reader(storage, app_name, verstr, name)(0, size)
            total += sum(k["n"] for h in read_headers(data) for k in h["keys"])
    return total


def _same_files(local, remote, app_name, verstr, objects, held):
    """The local ``.vmx`` files the remote holds as they are: same name, size
    and footer (the owner shipped its own compaction)."""
    sizes = dict(held)
    return {(n, size) for n, size in objects
            if is_indexed_file(n) and sizes.get(n) == size
            and _footer(local, app_name, verstr, n, size) == _footer(remote, app_name, verstr, n, size)}


def _covered(local, remote, app_name, verstr, objects, held):
    """Whether the remote objects *held* (one stream's, with a ``.vmx``)
    provably hold every point of the local *objects*: files the remote holds
    as they are, and otherwise as many points — both are prefixes of the one
    owner's stream (a remote ``.vmx`` with rewinds applied only counts fewer)."""
    same = _same_files(local, remote, app_name, verstr, objects, held)
    mine = [o for o in objects if o not in same]
    if not mine:
        return True
    past = max((covered_seq(n) for n, _ in held if is_indexed_file(n)), default=-1)
    theirs = [o for o in held if o not in same]
    return (_points(remote, app_name, verstr, theirs, local=False, past=past)
            >= _points(local, app_name, verstr, mine))


def _lacks_metrics(local, remote, app_name, verstr, objects, theirs):
    if any(is_indexed_file(n) for n, _ in theirs):
        return not _covered(local, remote, app_name, verstr, objects, theirs)
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
        missing |= {s for s, o in metrics.items() if _lacks_metrics(
            local, remote, app_name, verstr, o, remote_objects.get(s, []))}
    return sorted(missing)


def inherited_note(app_name, verstr, streams):
    return (f"{len(streams)} stream(s) of this record came from another checkout or "
            f"another view of this folder (e.g. a container mounting it at another path) "
            f"({', '.join(streams)}) and the remote lacks part of them; only their owner "
            f"pushes them. Once that one will never write again, run "
            f"`vmn-exp push {app_name} -v {verstr} --adopt`")


def note_missing_inherited(local, remote, app_name, verstr):
    """Warn about what the remote lacks of the copy's inherited streams, from
    one listing per run and process (advice only: a failed listing is not
    reported, and is tried again)."""
    key = (local.local_record_dir(app_name, verstr), app_name, verstr)
    if key in _LISTED:
        return
    try:
        streams = missing_inherited(local, remote, app_name, verstr)
    except Exception:
        VMN_LOGGER.debug("Listing inherited streams failed", exc_info=True)
        return
    _LISTED.add(key)
    if streams:
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
        remote_metrics = _refuse_uncovered(local, remote, app_name, verstr, theirs)
        _catch_up_logs(local, remote, app_name, verstr, record, theirs)
        _catch_up_metrics(local, remote, app_name, verstr, record, theirs, remote_metrics)
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


def _refuse_uncovered(local, remote, app_name, verstr, theirs):
    """The remote's metric objects; raises, before anything is changed, when
    a remote ``.vmx`` of an inherited stream lacks points of the copy's."""
    remote_objects = remote.metric_objects(app_name, verstr)
    for stream, objects in local.metric_objects(app_name, verstr).items():
        held = remote_objects.get(stream, [])
        if (theirs(stream) and any(is_indexed_file(n) for n, _ in held)
                and not _covered(local, remote, app_name, verstr, objects, held)):
            raise ValueError(
                f"not adopting: the remote .vmx of stream {stream} lacks points this copy "
                f"holds (another checkout compacted what the original shipped); nothing "
                f"changed. Push from the original checkout if it still exists, else those "
                f"points stay in this copy only")
    return remote_objects


def _catch_up_metrics(local, remote, app_name, verstr, record, theirs, remote_objects):
    for stream, objects in local.metric_objects(app_name, verstr).items():
        if not theirs(stream):
            continue
        held = remote_objects.get(stream, [])
        if any(is_indexed_file(n) for n, _ in held):
            # it holds every point of the copy's files (_refuse_uncovered)
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
