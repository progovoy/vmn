#!/usr/bin/env python3
"""Per-host SQLite index cache directory for S3-backed experiment storage.

Priority for the cache root:
  1. ``$VMN_INDEX_CACHE_DIR``  (value ``none`` / ``NONE`` disables → None)
  2. ``$XDG_CACHE_HOME/vmn``
  3. ``~/.cache/vmn``

``s3_index_cache_path(endpoint_url, bucket, prefix, app_name)`` returns the
path ``<root>/s3/<slug>.<hash12>/<safe_app>/.index.sqlite``, where the key is
derived from endpoint/bucket/prefix so distinct combinations never collide and
path traversal (``..``, ``/``) in any component is impossible.
"""
import functools
import hashlib
import os
import re

_verified_dirs: set = set()


def index_cache_root():
    """The root dir for cached S3 indexes, or None when disabled."""
    env = os.environ.get("VMN_INDEX_CACHE_DIR")
    if env is not None:
        return None if env.lower() == "none" else env
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "vmn")


def _slug(s):
    """ASCII-safe slug; keeps only ``[a-zA-Z0-9_-]``."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:48]


@functools.lru_cache(maxsize=None)
def _bucket_key(endpoint_url, bucket, prefix):
    """``<readable_slug>.<sha256_12>`` for the (endpoint, bucket, prefix) triple.

    The SHA-256 ensures distinct triples always map to distinct keys even if
    their slugs collide.  The readable slug is the bucket name, sanitised.
    Cached per unique triple so repeated index builds cost no rehashing.
    """
    raw = f"{endpoint_url or ''}|{bucket or ''}|{prefix or ''}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"{_slug(bucket)}.{digest}"


def _ensure_writable_dir(path):
    """Create *path* and verify it is writable. Returns True on success.

    Skips the probe on paths already verified in this process.
    """
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


def s3_index_cache_path(endpoint_url, bucket, prefix, app_name):
    """Persistent SQLite index path for *app_name* on this S3 configuration.

    Returns None when:
    - the cache root is disabled (``VMN_INDEX_CACHE_DIR=none``),
    - the root directory cannot be created or written to.

    Path traversal in *prefix* or *app_name* (``..``, ``/``) is neutralised:
    *prefix* is folded into the keyed hash; *app_name* is slugged.
    """
    root = index_cache_root()
    if root is None:
        return None
    key = _bucket_key(endpoint_url, bucket, prefix)
    safe_app = _slug(app_name.replace("/", "-"))
    cache_dir = os.path.join(root, "s3", key, safe_app)
    if not _ensure_writable_dir(cache_dir):
        return None
    return os.path.join(cache_dir, ".index.sqlite")
