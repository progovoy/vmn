#!/usr/bin/env python3
"""The S3 backend's client and key helpers, shared by its listing, record and
log halves (:mod:`snapshot_storage_s3`)."""

import copy
from concurrent.futures import ThreadPoolExecutor

from vmn_exp._base import VMN_LOGGER
from vmn_exp.storage.files import (
    METADATA_FILE,
    checked_app_path,
    safe_verstr,
)
from vmn_exp.storage.registry import missing_extra

# Requests one call keeps in flight: enough to hide S3 latency at 10k+ runs,
# few enough to fit boto3's default connection pool (10 per client).
S3_WORKERS = 10
MISSING_CODES = ("404", "NoSuchKey", "NotFound")
TAKEN_CODES = ("412", "PreconditionFailed", "409", "ConditionalRequestConflict")


def error_code(exc):
    return ((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code")


def is_missing(exc):
    """Whether *exc* says the object does not exist (not an access/transport error)."""
    return error_code(exc) in MISSING_CODES or "NoSuchKey" in str(exc)


def is_taken(exc):
    """Whether *exc* is a failed write precondition (someone else got there)."""
    return error_code(exc) in TAKEN_CODES


def parallel_map(fn, items):
    """``[fn(item)]`` in order, at most :data:`S3_WORKERS` at a time."""
    items = list(items)
    if len(items) < 2:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(S3_WORKERS, len(items))) as pool:
        return list(pool.map(fn, items))


def app_keys(app_name):
    """The app's key segment, then the legacy one when it differs."""
    new, legacy = app_name.replace("/", "-"), app_name.replace("/", "_")
    return [new] if new == legacy else [new, legacy]


def boto3_client(endpoint_url=None):
    return boto3_client_module().client("s3", **({"endpoint_url": endpoint_url} if endpoint_url else {}))


def sigv4_client(endpoint_url=None):
    """A client that presigns with SigV4 (``X-Amz-Expires`` bounded URLs)."""
    from botocore.config import Config

    kwargs = {"endpoint_url": endpoint_url} if endpoint_url else {}
    return boto3_client_module().client("s3", config=Config(signature_version="s3v4"), **kwargs)


def boto3_client_module():
    try:
        import boto3
    except ImportError:
        raise missing_extra("boto3", "s3") from None
    return boto3


class S3Base:
    """``client`` speaks the boto3 S3 client subset these halves use; other
    object stores pass an adapter (:mod:`vmn_exp.storage.object_client`)."""

    scheme = "s3"

    def __init__(self, bucket, prefix="vmn/snapshots", endpoint_url=None, client=None):
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_url = endpoint_url
        self._s3 = client or boto3_client(endpoint_url)
        self._record_prefixes = {}
        self._probes = {}
        self._legacy_owners = {}

    @property
    def area(self):
        return self.prefix.rpartition("/")[2]

    def _open_area(self, name):
        """This store's sibling area: ``<root>/<name>``, sharing the client."""
        clone = copy.copy(self)
        clone.__dict__.pop("_areas", None)
        clone.prefix = f"{self.prefix.rpartition('/')[0]}/{name}".lstrip("/")
        clone._record_prefixes, clone._probes, clone._legacy_owners = {}, {}, {}
        return clone

    # -- keys -----------------------------------------------------------------

    def _key_prefix(self, app_name, verstr=None, app_key=None):
        base = f"{self.prefix}/{app_key or app_keys(checked_app_path(app_name))[0]}"
        return f"{base}/{safe_verstr(verstr)}" if verstr else base

    def _record_prefix(self, app_name, verstr):
        """Where *verstr*'s objects live: the current key, or the legacy one
        for a record written before the encoding changed."""
        keys = app_keys(app_name)
        if len(keys) == 1:
            return self._key_prefix(app_name, verstr)
        cached = self._record_prefixes.get((app_name, verstr))
        if cached:
            return cached
        for key in keys:
            prefix = self._key_prefix(app_name, verstr, app_key=key)
            if self._head(f"{prefix}/{METADATA_FILE}"):
                self._record_prefixes[(app_name, verstr)] = prefix
                return prefix
        return self._key_prefix(app_name, verstr)

    # -- client ---------------------------------------------------------------

    def _head(self, key):
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            if not is_missing(e):
                VMN_LOGGER.warning(f"S3 error checking {key}: {e}")
            return False

    def _get(self, key):
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as e:
            if not is_missing(e):
                VMN_LOGGER.debug(f"S3 error reading {key}", exc_info=True)
            return None

    def _get_or_raise(self, key):
        """*key*'s bytes, None when it is missing; any other failure raises."""
        return self._get_with_etag(key)[0]

    def _get_with_etag(self, key):
        """``(bytes, etag)`` of *key*, ``(None, None)`` when it is missing."""
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if is_missing(e):
                return None, None
            raise
        return resp["Body"].read(), resp["ETag"]

    def _put(self, key, data, **kwargs):
        body = data.encode("utf-8") if isinstance(data, str) else data
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, **kwargs)

    def _pages(self, **params):
        """Every ``list_objects_v2`` page for *params*, following continuations."""
        params = dict(params, Bucket=self.bucket)
        while True:
            page = self._s3.list_objects_v2(**params)
            yield page
            if not page.get("IsTruncated"):
                return
            params["ContinuationToken"] = page["NextContinuationToken"]

    def _objects(self, prefix):
        for page in self._pages(Prefix=prefix):
            yield from page.get("Contents", [])

    def _common_prefixes(self, prefix):
        found = []
        for page in self._pages(Prefix=prefix, Delimiter="/"):
            found.extend(cp["Prefix"] for cp in page.get("CommonPrefixes", []))
        return found
