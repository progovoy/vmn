"""The real IO of finding, locking and removing this host's log buffers
(:mod:`vmn_exp.core.buffer_recover` takes it as a parameter; plan 40 C6)."""
import json
import os
import shutil
import socket

from vmn_exp.storage import buffer_owner
from vmn_exp.storage.fs_type import filesystem_type, is_network_fs
from vmn_exp.storage.local import LocalSnapshotStorage


class LocalBufferHost:
    """Buffer dirs on this host's filesystem. ``try_lock`` is None where
    there is no ``fcntl``: no buffer's owner lock can be taken."""

    try_lock = staticmethod(buffer_owner.take_lock) if buffer_owner.fcntl else None

    def list_dirs(self, path):
        """The subdirectories of *path*, sorted (none when it is missing)."""
        try:
            names = sorted(os.listdir(path))
        except OSError:
            return []
        return [os.path.join(path, n) for n in names if os.path.isdir(os.path.join(path, n))]

    def read_marker(self, root):
        """*root*'s owner marker, or None (missing or unreadable)."""
        try:
            with open(os.path.join(root, buffer_owner.MARKER_FILE)) as f:
                marker = json.load(f)
        except (OSError, ValueError):
            return None
        return marker if isinstance(marker, dict) else None

    def has_lock_file(self, root):
        return os.path.exists(os.path.join(root, buffer_owner.LOCK_FILE))

    def records(self, root, area):
        """``[(app, verstr)]`` of the records buffered under *root*."""
        local = LocalSnapshotStorage(root, area)
        return [(app, verstr) for app in local.list_apps() for verstr in local.list_verstrs(app)]

    def size(self, root):
        return sum(
            os.path.getsize(os.path.join(d, name))
            for d, _, names in os.walk(root)
            for name in names
        )

    def remove_tree(self, root):
        shutil.rmtree(root, ignore_errors=True)

    def hostname(self):
        return socket.gethostname()

    def on_network_fs(self, path):
        return is_network_fs(filesystem_type(path))
