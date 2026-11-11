"""Kept or orphaned direct-to-bucket log buffers: list them, ship them
(plan 40 C6, ``vmn-exp buffers list|ship``).

A buffer is shipped only by a process that holds its owner lock
(:mod:`vmn_exp.storage.buffer_owner`), which it gets only once the owning
process is gone or gave the buffer up: a live owner's buffer is listed, never
opened, shipped or removed from outside. A dir with no marker or no lock file
(kept before buffers had owners, or not a buffer) is unknown: nothing proves
its owner is gone. Shipping resumes each stream from what the remote holds,
then publishes a final state only the buffer holds; a run killed before it
ended keeps its state (it reads stuck until ``vmn-exp finish``).

All IO goes through *host* (:class:`~vmn_exp.storage.buffer_host.LocalBufferHost`).
"""
from collections import namedtuple
from dataclasses import dataclass, field

from vmn_exp.storage.buffer_state import unpublished_final_states
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.cached import local_side

SHIPPED, LIVE, UNKNOWN, NO_LOCK, FAILED = "shipped", "live", "unknown", "no-lock", "failed"

Outcome = namedtuple("Outcome", "status detail")


_MARKER_FIELDS = ("pid", "host", "started_at", "remote", "area")


@dataclass
class KeptBuffer:
    root: str
    marker: dict = None  # None: unknown, never shipped nor removed
    live: bool = None  # None: unknown (no marker or lock file, or no locking here)
    why: str = ""
    runs: list = field(default_factory=list)
    size: int = 0
    pid: int = None
    host: str = None
    started_at: str = None
    remote: str = None  # repr of the store's cache_identity()
    area: str = None


def kept_buffers(bases, host):
    """The buffer dirs under each of *bases* (``<base>/<store id>/<buffer>``)."""
    return [
        _describe(root, host)
        for base in bases
        for store_dir in host.list_dirs(base)
        for root in host.list_dirs(store_dir)
    ]


def _describe(root, host):
    marker = host.read_marker(root)
    if marker is None or not host.has_lock_file(root):
        return KeptBuffer(root, why="no owner marker or lock", size=host.size(root))
    buffer = KeptBuffer(root, marker, runs=host.records(root, marker.get("area")),
                        size=host.size(root), **{k: marker.get(k) for k in _MARKER_FIELDS})
    foreign = _foreign_on_network_fs(buffer, host)
    if foreign:
        buffer.live, buffer.why = True, foreign
    elif host.try_lock is None:
        buffer.why = "no file locking on this platform"
    else:
        lock = host.try_lock(root)
        buffer.live = lock is None
        if lock is not None:
            lock.release()
    return buffer


def _foreign_on_network_fs(buffer, host):
    """Why *buffer* counts as live although its lock might be free: on a
    network filesystem a lock may not exclude another host's owner."""
    if buffer.host != host.hostname() and host.on_network_fs(buffer.root):
        return f"on a network filesystem and owned by host {buffer.host}"
    return ""


def ship_buffer(buffer, remote, host, keep=False):
    """Ship what *buffer* holds to *remote* under its owner lock, then
    remove it (unless *keep*); the :class:`Outcome`."""
    if buffer.marker is None:
        return Outcome(UNKNOWN, buffer.why)
    if buffer.live:
        return Outcome(LIVE, buffer.why)
    if host.try_lock is None:
        return Outcome(NO_LOCK, "no file locking on this platform")
    lock = host.try_lock(buffer.root)
    if lock is None:
        return Outcome(LIVE, "")
    try:
        _ship_locked(buffer, remote)
        if not keep:
            lock.release()  # first: an open fd on NFS leaves a .nfsXXXX behind
            host.remove_tree(buffer.root)
        return Outcome(SHIPPED, "")
    except Exception as exc:
        return Outcome(FAILED, exc)
    finally:
        lock.release()


def _ship_locked(buffer, remote):
    storage = BufferedRemoteStorage.reopen(buffer.root, remote, buffer.area)
    for app_name, verstr in buffer.runs:
        storage.sync_log_to_remote(app_name, verstr, None)
        storage.sync_metrics_to_remote(app_name, verstr, None)
    unpublished = unpublished_final_states(local_side(storage), remote)
    if unpublished:
        raise RuntimeError(f"the final state of {', '.join(unpublished)} was not published")
