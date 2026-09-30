"""Storage backends keyed by URI scheme.

Built-ins: ``file`` (local disk), ``s3``, ``gs`` (``vmn-exp-sdk[gcs]``) and
``az`` (``vmn-exp-sdk[azure]``). Other packages add schemes under the
``vmn_exp.storage`` entry-point group::

    [project.entry-points."vmn_exp.storage"]
    mem = "my_pkg.store:open_store"

A factory is called as ``factory(uri, subdir=...)`` with the parsed
:class:`~vmn_exp.storage.uri.StoreURI` and ``"experiments"``/``"snapshots"``,
and returns a :class:`~vmn_exp.storage.base.SnapshotStorage`. See
docs/vmn-exp/experiments.md ("Storage backends") for the contract it must meet.
"""
from importlib import import_module
from importlib.metadata import entry_points

from vmn_exp.storage.uri import parse_store_uri

ENTRY_POINT_GROUP = "vmn_exp.storage"

_BUILTINS = {
    "file": "vmn_exp.storage.registry:open_file_store",
    "s3": "vmn_exp.storage.registry:open_s3_store",
    "gs": "vmn_exp.storage.gcs:open_gcs_store",
    "az": "vmn_exp.storage.azure:open_azure_store",
}

_registered = {}
_entry_points_loaded = False


def missing_extra(package, extra):
    return ImportError(
        f"{package} is required for this storage backend. "
        f"Install it with: pip install 'vmn-exp-sdk[{extra}]'"
    )


def default_prefix(uri, subdir):
    """The URI's key prefix, else ``vmn-<subdir>``."""
    return uri.path or f"vmn-{subdir}"


def register_store(scheme, factory):
    """Serve *scheme* URIs with *factory* (a callable or ``"module:attr"``)."""
    _registered[scheme.lower()] = factory


def known_schemes():
    _load_entry_points()
    return sorted(set(_BUILTINS) | set(_registered))


def open_store(uri, subdir="experiments"):
    """The backend storage *uri* names (a string or a parsed ``StoreURI``)."""
    parsed = parse_store_uri(uri) if isinstance(uri, str) else uri
    return _factory(parsed.scheme)(parsed, subdir=subdir)


def _factory(scheme):
    _load_entry_points()
    target = _registered.get(scheme) or _BUILTINS.get(scheme)
    if target is None:
        raise ValueError(
            f"Unknown storage scheme {scheme!r}. Known: {', '.join(known_schemes())}. "
            f"Packages add schemes under the {ENTRY_POINT_GROUP!r} entry-point group."
        )
    return _resolve(target) if isinstance(target, str) else target


def _resolve(target):
    module, _, attr = target.partition(":")
    return getattr(import_module(module), attr)


def _storage_entry_points():
    found = entry_points()
    if hasattr(found, "select"):
        return list(found.select(group=ENTRY_POINT_GROUP))
    return list(found.get(ENTRY_POINT_GROUP, []))  # Python < 3.10


def _load_entry_points():
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    for ep in _storage_entry_points():
        _registered.setdefault(ep.name.lower(), _LazyEntryPoint(ep))


class _LazyEntryPoint:
    """Loads its entry point on first use, so a broken plugin only fails the
    URIs that name its scheme."""

    def __init__(self, ep):
        self._ep = ep

    def __call__(self, uri, subdir):
        try:
            factory = self._ep.load()
        except ImportError as e:
            raise ImportError(
                f"Storage plugin {self._ep.name!r} ({self._ep.value}) failed to load: {e}"
            ) from e
        return factory(uri, subdir=subdir)


# -- built-in factories -------------------------------------------------------


def open_file_store(uri, subdir):
    from vmn_exp.storage.local import LocalSnapshotStorage

    return LocalSnapshotStorage(uri.path, subdir=subdir)


def open_s3_store(uri, subdir):
    from vmn_exp.storage.s3 import S3SnapshotStorage

    return S3SnapshotStorage(
        uri.location,
        prefix=default_prefix(uri, subdir),
        endpoint_url=uri.options.get("endpoint_url"),
    )
