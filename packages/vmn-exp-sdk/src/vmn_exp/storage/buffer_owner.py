"""A log buffer's owner marker and owner lock (plan 40 C5).

The first write into a buffer dir writes ``buffer.json`` (whose process,
host and store it is) and takes a non-blocking exclusive ``flock`` on
``.buffer-owner.lock``, held for as long as the process owns the buffer: a
buffer whose lock can be taken belongs to no live process. The lock keeps an
fd of its own, outside :mod:`~vmn_exp.storage.ship_state`'s lock fds (those
are scoped to a ``with`` block and closed when not held). A forked child
closes the copies it inherited, so it never holds its parent's lock; where
``fcntl`` is missing no lock is taken.
"""
import json
import os
import socket
import time

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

from vmn_exp.storage.files import atomic_write
from vmn_exp.storage.local import LocalSnapshotStorage

MARKER_FILE = "buffer.json"
LOCK_FILE = ".buffer-owner.lock"

_HELD = set()  # the OwnerLocks this process holds


class OwnerLock:
    """A held owner lock; :meth:`release` is idempotent."""

    def __init__(self, fd):
        self.fd = fd
        _HELD.add(self)

    def release(self):
        if self.fd is not None:
            _HELD.discard(self)
            os.close(self.fd)  # the last fd on the open file: the flock goes
            self.fd = None


def claim(root, remote, area):
    """Mark *root* as this process's buffer of *remote*'s *area* and take its
    owner lock: the :class:`OwnerLock`, or None (no ``fcntl``, or held)."""
    marker = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "remote": repr(remote.cache_identity()),
        "area": area,
    }
    atomic_write(os.path.join(root, MARKER_FILE), json.dumps(marker))
    return take_lock(root)


def take_lock(root):
    """*root*'s owner lock if it can be taken at once, else None."""
    if fcntl is None:
        return None
    fd = os.open(os.path.join(root, LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return OwnerLock(fd)


class BufferDir(LocalSnapshotStorage):
    """The local store of a buffer of *remote*: a write that finds its root
    unmarked (its first, or the first after a cleanup) claims it."""

    def __init__(self, root, area, remote):
        super().__init__(root, area)
        self._remote = remote
        self.owner_lock = None

    def _ensure_base_dir(self, app_name):
        base = super()._ensure_base_dir(app_name)
        if not os.path.exists(os.path.join(self.root, MARKER_FILE)):
            self.release()
            self.owner_lock = claim(self.root, self._remote, self.area)
        return base

    def release(self):
        """Give the owner lock up (idempotent)."""
        if self.owner_lock is not None:
            self.owner_lock.release()


def _close_inherited():
    """In a forked child: its fds share the parent's open files, whose locks
    stay the parent's; the child drops its copies."""
    while _HELD:
        lock = _HELD.pop()
        os.close(lock.fd)
        lock.fd = None


if fcntl is not None and hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_close_inherited)
