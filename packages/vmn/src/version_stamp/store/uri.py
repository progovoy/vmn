"""Storage URIs: ``<scheme>://<location>/<path>[?option=value...]``.

``s3://bucket/prefix``, ``gs://bucket/prefix``, ``az://container/prefix``,
``file:///abs/dir`` (or a bare path). The scheme picks the backend
(:mod:`vmn_exp.storage.registry`); the query string carries backend options
such as ``?endpoint_url=http://minio:9000``.
"""
import os
from dataclasses import dataclass, field
from typing import Dict
from urllib.parse import parse_qsl, urlencode, urlsplit


@dataclass(frozen=True)
class StoreURI:
    scheme: str
    location: str  # bucket / container; empty for file stores
    path: str  # key prefix without surrounding slashes; the directory for file
    options: Dict[str, str] = field(default_factory=dict)


def parse_store_uri(uri):
    if not uri:
        raise ValueError("Empty storage URI")
    if "://" not in uri:
        return StoreURI("file", "", os.path.abspath(os.path.expanduser(uri)))
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    options = dict(parse_qsl(parts.query))
    if scheme == "file":
        if parts.netloc not in ("", "localhost") or not parts.path:
            raise ValueError(f"A file store URI is file:///absolute/path, got {uri!r}")
        return StoreURI("file", "", parts.path, options)
    if not parts.netloc:
        raise ValueError(f"Storage URI {uri!r} names no bucket/container")
    return StoreURI(scheme, parts.netloc, parts.path.strip("/"), options)


def s3_uri(bucket, prefix=None, endpoint_url=None):
    """The ``s3://`` URI the ``--bucket/--prefix/--endpoint-url`` shorthand means."""
    uri = f"s3://{bucket}/{(prefix or '').strip('/')}".rstrip("/")
    if endpoint_url:
        uri += "?" + urlencode({"endpoint_url": endpoint_url})
    return uri
