"""Which filesystem a path lives on (plan 25 §2: no SQLite cache on NFS).

macOS: ``statfs(2)``'s ``f_fstypename`` through ctypes (``os.statvfs`` has no
type). Linux: the longest mount point of ``/proc/mounts`` above the path.
Elsewhere, or on any failure: None (treated as local). A path not created
yet has its nearest existing parent's type.
"""
import ctypes
import ctypes.util
import functools
import os
import sys

NETWORK_FS = frozenset({
    "nfs", "nfs4", "cifs", "smb", "smb2", "smb3", "smbfs", "afpfs", "webdav",
    "fuse.sshfs", "sshfs", "9p", "afs", "ncpfs", "lustre", "gpfs", "glusterfs",
    "fuse.glusterfs", "ceph", "fuse.ceph",
})

# struct statfs (64-bit inodes) up to f_fstypename: u32 f_bsize, i32 f_iosize,
# 5 x u64 counts, fsid_t (2 x i32), uid_t f_owner, u32 f_type, f_flags,
# f_fssubtype; then char f_fstypename[16], f_mntonname[1024],
# f_mntfromname[1024], u32 f_flags_ext, u32 f_reserved[7].
_MAC_FSTYPENAME_OFFSET = 72
_MAC_STATFS_SIZE = 72 + 16 + 1024 + 1024 + 4 + 28


def is_network_fs(kind):
    return bool(kind) and kind.lower() in NETWORK_FS


def _existing(path):
    path = os.path.abspath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return os.path.realpath(path)


@functools.lru_cache(maxsize=64)
def filesystem_type(path):
    """The type name of the filesystem holding *path*, or None."""
    try:
        target = _existing(path)
        if sys.platform == "darwin":
            return _mac_fs_type(target)
        if sys.platform.startswith("linux"):
            with open("/proc/mounts") as f:
                return fs_type_from_mounts(f.read(), target)
    except (OSError, ValueError, AttributeError):
        pass
    return None


@functools.lru_cache(maxsize=None)
def _mac_statfs():
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    return getattr(libc, "statfs$INODE64", None) or libc.statfs  # x86_64 / arm64


def _mac_fs_type(path):
    statfs = _mac_statfs()
    buf = ctypes.create_string_buffer(_MAC_STATFS_SIZE)
    if statfs(os.fsencode(path), buf) != 0:
        return None
    raw = buf.raw[_MAC_FSTYPENAME_OFFSET:_MAC_FSTYPENAME_OFFSET + 16]
    return raw.split(b"\0", 1)[0].decode() or None


def _unescape(field):
    """``/proc/mounts`` octal-escapes spaces, tabs and backslashes."""
    return field.encode().decode("unicode_escape") if "\\" in field else field


def fs_type_from_mounts(mounts, path):
    """The type of the longest mount point in *mounts* (``/proc/mounts``
    text) at or above *path*."""
    best, kind = -1, None
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        point = _unescape(fields[1]).rstrip("/") or "/"
        inside = point == "/" or path == point or path.startswith(point + "/")
        if inside and len(point) > best:
            best, kind = len(point), fields[2]
    return kind
