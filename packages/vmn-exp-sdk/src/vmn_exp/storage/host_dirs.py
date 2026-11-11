"""Per-host dirs for state that never belongs in a store (plan 14 §1.4).

- cache (rebuildable): ``$XDG_CACHE_HOME/vmn-exp`` (macOS
  ``~/Library/Caches/vmn-exp``, else ``~/.cache/vmn-exp``). The experiment
  index lives at ``<cache>/index/<store-id>/<app>.sqlite``; legacy
  ``$VMN_INDEX_CACHE_DIR`` still overrides its root (``none`` disables it).
- state (worth keeping): ``$XDG_STATE_HOME/vmn-exp`` (macOS
  ``~/Library/Application Support/vmn-exp``, else ``~/.local/state/vmn-exp``).
  The push ledger lives at ``<state>/push/<store-id>/<remote_id>/<app>``,
  direct-to-bucket log buffers at ``<state>/log-buffers/<store-id>/<buffer>``
  (a state dir on a network filesystem or unwritable: a local temp dir).

``$VMN_EXP_CACHE_DIR`` replaces the base of both (containers). A default cache
dir on a network filesystem (NFS, SMB, sshfs: SQLite's locking and WAL are
unreliable there) is warned about once and replaced by a local temp dir; an
explicitly chosen dir is kept (:mod:`vmn_exp.storage.fs_type`). ``<store-id>``
is a stable hash of the backend's ``cache_identity()`` (a local root's
identity holds its absolute path), so two stores never share a file.
"""
import functools
import hashlib
import os
import re
import sys
import tempfile

from vmn_exp.core.best_effort import warn_once
from vmn_exp.storage.fs_type import filesystem_type, is_network_fs

_verified_dirs: set = set()


def _base(xdg_var, mac_parts, other_parts):
    override = os.environ.get("VMN_EXP_CACHE_DIR")
    if override:
        return override
    xdg = os.environ.get(xdg_var)
    if xdg:
        return os.path.join(xdg, "vmn-exp")
    parts = mac_parts if sys.platform == "darwin" else other_parts
    return os.path.join(os.path.expanduser("~"), *parts, "vmn-exp")


def _local_temp(name):
    """This user's *name* dir in the local temp dir."""
    uid = os.getuid() if hasattr(os, "getuid") else "user"
    return os.path.join(tempfile.gettempdir(), f"{name}-{uid}")


def cache_base():
    base = _base("XDG_CACHE_HOME", ("Library", "Caches"), (".cache",))
    if os.environ.get("VMN_EXP_CACHE_DIR"):
        return base
    kind = filesystem_type(base)
    if not is_network_fs(kind):
        return base
    fallback = _local_temp("vmn-exp-cache")
    warn_once((base, "network"), (
        f"The vmn-exp cache dir {base} is on a network filesystem ({kind}), where "
        f"SQLite is unreliable; using {fallback} instead (set VMN_EXP_CACHE_DIR "
        "to choose)"
    ))
    return fallback


def state_base():
    return _base(
        "XDG_STATE_HOME", ("Library", "Application Support"), (".local", "state")
    )


def _slug(s):
    """ASCII-safe slug; keeps only ``[a-zA-Z0-9_-]``."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:48]


@functools.lru_cache(maxsize=None)
def store_id(identity):
    """A stable, path-safe name for the store whose ``cache_identity()`` is
    *identity*."""
    return hashlib.sha256(repr(identity).encode()).hexdigest()[:24]


def _app_part(app_name):
    """Readable slug plus a short hash, so apps whose slugs collide (``a.b`` /
    ``a_b``, long names) never share a file."""
    digest = hashlib.sha256(app_name.encode()).hexdigest()[:8]
    return f"{_slug(app_name.replace('/', '-'))}.{digest}"


def index_cache_root():
    """The root dir for cached indexes, or None when disabled."""
    env = os.environ.get("VMN_INDEX_CACHE_DIR")
    if env is not None:
        return None if env.lower() == "none" else env
    return cache_base()


def ensure_writable_dir(path):
    """Create *path* and verify it is writable (once per process)."""
    if path in _verified_dirs:
        return True
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".vmn-write-test")
        with open(probe, "w") as f:
            f.write("")
        os.unlink(probe)
        _verified_dirs.add(path)
        return True
    except OSError:
        return False


def index_cache_path(identity, app_name):
    """The persistent SQLite index of *app_name* in the store *identity*, or
    None when caching is disabled or the dir is unwritable."""
    root = index_cache_root()
    if root is None or identity is None:
        return None
    cache_dir = os.path.join(root, "index", store_id(identity))
    if not ensure_writable_dir(cache_dir):
        return None
    return os.path.join(cache_dir, _app_part(app_name) + ".sqlite")


def _log_buffers_base():
    """Where log buffers go: ``$VMN_EXP_CACHE_DIR`` as given, else the state
    dir, unless that is on a network filesystem or unwritable (a buffer
    takes a write a second): then a local temp dir, warned about once."""
    override = os.environ.get("VMN_EXP_CACHE_DIR")
    if override:
        return override
    base = state_base()
    kind = filesystem_type(base)
    if is_network_fs(kind):
        why = f"is on a network filesystem ({kind})"
    elif not ensure_writable_dir(base):
        why = "is not writable"
    else:
        return base
    fallback = _local_temp("vmn-exp-state")
    warn_once((base, "log-buffers"), (
        f"The vmn-exp state dir {base} {why}; log buffers go to {fallback} "
        "instead (set VMN_EXP_CACHE_DIR to choose)"
    ))
    return fallback


def log_buffers_dir(identity):
    """The dir of the log buffers of the store whose ``cache_identity()`` is
    *identity*: one buffer per subdirectory."""
    return os.path.join(_log_buffers_base(), "log-buffers", store_id(identity))


def log_buffers_bases():
    """Every dir a log buffer of this host may be under (one subdirectory
    per store), for listing them."""
    bases = [os.environ.get("VMN_EXP_CACHE_DIR"), state_base(), _local_temp("vmn-exp-state")]
    found = [os.path.join(b, "log-buffers") for b in bases if b]
    return list(dict.fromkeys(found))


def push_ledger_dir(identity, remote_id, app_name):
    """Where the push ledger of *app_name* from store *identity* to the
    remote *remote_id* lives."""
    return os.path.join(
        state_base(), "push", store_id(identity), remote_id, _app_part(app_name)
    )
